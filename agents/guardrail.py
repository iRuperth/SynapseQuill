"""
guardrail.py — anti-hallucination guardrail for generated content (expert level).

Two layers:
  1. Deterministic facts check — verify the narration mentions the correct
     final score and does not name any scorer absent from the API data.
     This catches the worst failure mode (inventing goals) with zero cost.
  2. LLM-as-judge — a second model (ideally different from the generator)
     checks groundedness, language and tone, returning a structured verdict.

The narration must never invent scores/scorers — those come from API-Football.
"""

import json
import re

from json_repair import repair_json

from core.llm import call_llm
from pipeline.match_monitor import Match


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(ch))


def _fold(s: str) -> str:
    """Accent-folded casefold — the only normal form every check shares.
    Provider feeds ('Santiago Gimenez') and Spanish prose ('Giménez') differ
    in accents constantly, so matching on the folded text is the only reliable
    way to line a player's name up with how the narrator wrote it."""
    return _strip_accents(s.casefold())


def _name_windows(name: str, folded_text: str) -> list[tuple[int, int]]:
    """(start, end) of every mention of a player in the folded text. Tries the
    full name first, then the last token as a surname. Returns [] when the
    only usable token is too short to match safely (e.g. 'Son' -> the surname
    path is gated, but the full 'heung-min son' still matches if present)."""
    fname = _fold(name)
    spans = [(m.start(), m.end())
             for m in re.finditer(rf"\b{re.escape(fname)}\b", folded_text)]
    if spans:
        return spans
    surname = fname.split()[-1]
    if len(surname) < 4:
        return []
    return [(m.start(), m.end())
            for m in re.finditer(rf"\b{re.escape(surname)}\b", folded_text)]


def _all_name_spans(name: str, folded: str) -> list[tuple[int, int]]:
    """Every span where `name` is mentioned, full name AND bare surname.

    _name_windows deliberately stops at the full name when it finds one — for
    deciding whether a player was mentioned, the full name is the better
    evidence. This is the other question: where does someone ELSE's sentence
    start. A description that writes "Zaid Romero" once and "Romero" twice more
    is still talking about Romero at every one of them, and a boundary scan that
    only knew the first would let a neighbour's clause leak in.
    """
    spans = list(_name_windows(name, folded))
    surname = _fold(name).split()[-1]
    if len(surname) >= 4:
        spans += [(m.start(), m.end())
                  for m in re.finditer(rf"\b{re.escape(surname)}\b", folded)]
    return sorted(set(spans))


def _named_players(match: Match) -> list[str]:
    """Every player the match data names — scorers and carded players alike.

    These are the clause boundaries: whichever of them the prose turns to next
    is where the player being checked stops being the subject.
    """
    return list(dict.fromkeys([g.player for g in match.goals]
                              + [c.player for c in match.cards]))


def _clause_window(folded: str, s: int, e: int,
                   others: list[tuple[int, int]], span: int = 90) -> str:
    """The prose around one mention, stopping before the NEXT player's.

    A flat +/-90 characters was reading straight through a comma into somebody
    else's action, and every false hold it produced looked identical to a real
    one. "Johan Mojica, Zaid Romero y Ramon Terrats recibieron amarillos ...,
    mientras que Romero fue expulsado" reported Terrats as called red, on the
    strength of a sending-off the same sentence attributes to Romero by name;
    "Satriano ... con un disparo de derecho, pero Carl Starfelt igualo con un
    cabezazo" reported Satriano as headed.

    Clipping at the nearest other player NARROWS the evidence, which is the
    safe direction for a check that holds finished videos back: the cost is
    that a genuine error stated at arm's length from the name is left to the
    LLM judge, and the gain is that a correct description is not refused on the
    strength of a sentence about somebody else.
    """
    lo, hi = max(0, s - span), min(len(folded), e + span)
    for other_s, other_e in others:
        if other_e <= s:
            lo = max(lo, other_e)          # someone else, named before
        elif other_s >= e:
            hi = min(hi, other_s)          # someone else, named after
    return folded[lo:hi]


# Words that signal each card colour in the narration (Spanish + English).
# "amonest·ó/ado/ación" + "booked/caution" imply yellow; "expuls·ado/ión" /
# "sent off" / "roja" imply red. Deliberately NO bare "red" (matches Spanish
# "la red", the net). "roja" needs both boundaries (the surname "Rojas") AND a
# guard against "la roja" (Spain's nickname) — handled in _card_color_issues,
# not here, because the nickname only matters next to a Spain player's name.
_CARD_WORDS = {
    # \bamarill, not \bamarilla: a description that books three players at once
    # writes "recibieron amarillos", and the feminine-only pattern read that as
    # no yellow evidence at all — so the card fell through to the Red branch and
    # a correctly-described booking was reported as called red.
    "Yellow": re.compile(r"\bamarill|yellow|\bamonest|\bbooked\b|\bbooking\b|"
                         r"\bcaution", re.IGNORECASE),
    "Red": re.compile(r"\broja\b|\brojas\b|red card|\bexpuls|sent off",
                      re.IGNORECASE),
}
# "La Roja" / "la Roja" — Spain's (and Chile's) nickname, NOT a red card.
# Stripped from a window before the Red pattern runs so it can't masquerade as
# colour evidence in either direction (false flag on Spain, or false pass).
_TEAM_ROJA = re.compile(r"\bla roja\b", re.IGNORECASE)


def _card_color_issues(match: Match, text: str) -> list[str]:
    """Flag carded players whose mentions are surrounded ONLY by the wrong
    colour's words — e.g. a red card narrated as 'tarjeta amarilla'.

    A player PASSES if any mention sits near the correct colour. Players with
    cards of BOTH colours (second bookings) are skipped — either colour is
    fair. 'La Roja' (the team) is neutralised so it neither flags Spain nor
    hides a real miscolour."""
    issues = []
    folded = _fold(text)
    by_player: dict[str, set] = {}
    for c in match.cards:
        by_player.setdefault(c.player, set()).add(c.color)
    for player, colors in by_player.items():
        if len(colors) != 1:
            continue
        color = next(iter(colors))
        wrong = "Red" if color == "Yellow" else "Yellow"
        others = [sp for other in _named_players(match) if other != player
                  for sp in _all_name_spans(other, folded)]
        saw_wrong_only = saw_right = False
        for s, e in _name_windows(player, folded):
            window = _clause_window(folded, s, e, others)
            # Drop the team nickname so "la roja" is never red-card evidence.
            window = _TEAM_ROJA.sub(" ", window)
            if _CARD_WORDS[color].search(window):
                saw_right = True
                break
            if _CARD_WORDS[wrong].search(window):
                saw_wrong_only = True
        if saw_wrong_only and not saw_right:
            issues.append(f"{player}'s card is {color.lower()}, "
                          f"but the text calls it {wrong.lower()}")
    return issues


# How each goal was scored, from the provider's goal description. Only
# UNAMBIGUOUS body-part words count: bare "izquierda/derecha" also describe
# where the ball went ("al palo izquierdo"), so they never count as a foot.
# Run-direction prose ("de izquierda a derecha") is guarded with lookaheads,
# and "cabeza" alone is dropped (it appears in "levantó la cabeza", a
# look-up, and "despeje de cabeza", a clearance) — only header-specific forms
# count. Note: patterns run on ACCENT-FOLDED text, so no accents in them.
_BODY_WORDS = {
    # "de derech[ao]" / "de izquierd[ao]": Spanish says BOTH "de derecha" and
    # "un disparo de derecho" for the same right-footed shot, and only the
    # feminine was listed — so a description that got the foot right was read as
    # describing no foot at all, and then as the wrong body part.
    "right": re.compile(r"\bderechazo|\bdiestra\b|pierna derecha|"
                        r"con (?:la|su) derecha|de derech[ao]\b(?! a izquierda)",
                        re.IGNORECASE),
    "left": re.compile(r"\bzurd|pierna izquierda|"
                       r"con (?:la|su) izquierda|de izquierd[ao]\b(?! a derecha)",
                       re.IGNORECASE),
    "header": re.compile(r"de cabeza\b|cabezazo|\bcabece|\btestarazo\b|"
                         r"\bfrentazo\b|header", re.IGNORECASE),
}

# Penalty / own-goal vocabulary. These run on ACCENT-FOLDED text, so no
# accents appear in the patterns ("pena maxima", "porteria"). "area penal" is
# a PLACE on the pitch, not a penalty kick — excluded with a lookbehind.
_PEN_WORDS = re.compile(r"\bpenalti|\bpenalty|(?<!area )\bpenal\b|"
                        r"pena maxima|once metros|desde el punto",
                        re.IGNORECASE)
# "propio gol" also describes an own goal — the narrator uses it freely, so it
# must count or a genuine own-goal narration trips the guardrail. CAREFUL: a
# bare "en su propia area/zona" is just a PLACE (a clearance happens there too),
# so it is deliberately NOT matched — only own-goal-specific forms are, to avoid
# the inverse false-positive ("mentions an own goal" where there was none).
_OWN_WORDS = re.compile(r"autogol|propi[oa] (?:puerta|meta|porteria)|"
                        r"\bel propio gol\b|en propia\b|en propias? mallas|"
                        r"own goal|gol en contra", re.IGNORECASE)

# A penalty mention that is NEGATED — the VAR/referee waved it away. "VAR
# Decision: No Penalty" is a real moment, so the narrator rightly says "no penal"
# / "sin penal" / "no fue penal" / "sin encontrar penal"; that must NOT count as
# an invented penalty goal. Runs on ACCENT-FOLDED text, so no accents here.
# Covers the negator-BEFORE-penal forms ESPN's "No Penalty" note produces (a few
# words may sit between: "no hubo penal", "no señala penal", "sin encontrar
# penal"). A trailing negation ("penal, pero el árbitro dice que no") is rarer
# and left to the LLM-judge layer, to avoid masking a real penalty goal that
# happens to be followed by an unrelated "no".
_NEGATED_PEN = re.compile(
    r"\b(?:no|sin)\b(?:\s+\w+){0,3}?\s+penal(?:ti|ty)?\b", re.IGNORECASE)


def _goal_kind(description: str) -> str | None:
    """'right' / 'left' / 'header' from an ESPN-style goal description."""
    d = description.lower()
    if "header" in d:
        return "header"
    if "right footed" in d:
        return "right"
    if "left footed" in d:
        return "left"
    return None


def _goal_detail_issues(match: Match, text: str) -> list[str]:
    """Flag scorers narrated with the WRONG body part — a right-footed shot
    sold as 'disparo de zurda', a header turned into a shot, etc.

    Players who scored goals of DIFFERENT kinds in the same match (a brace of
    a header + a footed goal) are skipped: the narration may legitimately name
    only one finish, and the other word would false-flag. Cross-actor foot
    prose (the crosser's, the keeper's) is the residual risk the LLM judge
    backstops — the deterministic layer only fires when a mention is near a
    wrong word AND never near the right one."""
    issues = []
    folded = _fold(text)
    kinds_by_player: dict[str, set] = {}
    for g in match.goals:
        k = _goal_kind(g.description or "")
        if k:
            kinds_by_player.setdefault(g.player, set()).add(k)
    for g in match.goals:
        kind = _goal_kind(g.description or "")
        if kind is None:
            continue
        if len(kinds_by_player.get(g.player, set())) != 1:
            continue                              # mixed-finish brace — skip
        wrong_kinds = [k for k in _BODY_WORDS if k != kind]
        # Everyone else the match data names bounds how far this scorer's
        # prose can reach.
        others = [sp for other in _named_players(match) if other != g.player
                  for sp in _all_name_spans(other, folded)]
        saw_wrong_only = saw_right = False
        for s, e in _name_windows(g.player, folded):
            window = _clause_window(folded, s, e, others)
            if _BODY_WORDS[kind].search(window):
                saw_right = True
                break
            if any(_BODY_WORDS[k].search(window) for k in wrong_kinds):
                saw_wrong_only = True
        if saw_wrong_only and not saw_right:
            human = {"right": "right foot", "left": "left foot",
                     "header": "header"}[kind]
            issues.append(f"{g.player}'s goal was a {human}, "
                          f"but the text describes a different body part")
    return issues


def _goal_type_issues(match: Match, text: str) -> list[str]:
    """Penalties and own goals must be narrated AS penalties and own goals —
    and never invented where there were none.

    The REQUIRED direction is per-scorer (window around the name). The
    INVENTED direction is match-level only: adjacent goals share prose, so a
    neighbour's genuine 'penalti' lands in this scorer's window and a
    per-scorer check would false-flag it."""
    issues = []
    folded = _fold(text)
    # A penalty only becomes a GOAL when it is scored. One that is saved, missed
    # or merely awarded lives in the event notes ("Penalty saved. Andrés Martín
    # ... saved by David Soria"), and the facts block hands those to the narrator
    # to narrate — so a narration that mentions them is being FAITHFUL. Reading
    # goals alone flagged that as an invented penalty and burned all three
    # regeneration attempts on prose that was right the first time.
    has_pen = (any("Pen" in (g.kind or "") for g in match.goals)
               or any(_PEN_WORDS.search(_fold(n)) for n in (match.notes or [])))
    has_own = any("Own" in (g.kind or "") for g in match.goals)
    shootout = match.home_pens is not None or match.away_pens is not None
    # A NEGATED penalty ("el VAR revisa sin encontrar penal", "no fue penal", "no
    # señala penal") is a real moment ESPN reports ("VAR Decision: No Penalty"),
    # NOT an invented penalty goal. Blank those mentions before the invention
    # check so a faithfully-narrated no-penalty VAR call doesn't false-fail.
    pen_check = _NEGATED_PEN.sub(" ", folded)
    if not has_pen and not shootout and _PEN_WORDS.search(pen_check):
        issues.append("the text mentions a penalty but no goal was a penalty")
    if not has_own and _OWN_WORDS.search(folded):
        issues.append("the text mentions an own goal but none was scored")
    for g in match.goals:
        is_pen = "Pen" in (g.kind or "")
        is_own = "Own" in (g.kind or "")
        if not (is_pen or is_own):
            continue
        spans = _name_windows(g.player, folded)
        if not spans:
            continue                              # scorer never named
        windows = [folded[max(0, s - 90): e + 90] for s, e in spans]
        if is_pen and not any(_PEN_WORDS.search(w) for w in windows):
            issues.append(f"{g.player}'s goal was a PENALTY but the text "
                          "never says so")
        if is_own and not any(_OWN_WORDS.search(w) for w in windows):
            issues.append(f"{g.player}'s goal was an OWN GOAL but the text "
                          "never says so")
    return issues


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(ch))


def _edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein with a small cap (band optimisation is overkill here)."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# Capitalised Spanish words that routinely sit a single edit away from a real
# surname (¡Vamos!~Ramos, Goles~Gomes, etc.). The narrator is told to use
# exclamations, so these WILL appear — never treat them as misspellings.
_NOT_A_TYPO = {
    "vamos", "goles", "golazo", "remate", "equipo", "minuto", "partido",
    "ataque", "afuera", "fuera", "dentro", "ahora", "bienvenidos", "increible",
    "imparable", "definitivo", "marcador", "delantero", "victoria", "ataja",
    "primera", "segunda", "tercera", "cuarta", "quinta", "ultima", "media",
    "espana", "francia", "brasil", "mexico", "japon", "ataca",
}


def _name_spelling_issues(match: Match, text: str) -> list[str]:
    """Flag NEAR-MISS spellings of known player names ('César Montaes' for
    'César Montes'): the voice reads the typo aloud.

    Conservative by design — a false flag burns up to 3 regenerations on a
    correct narration. So a candidate is flagged ONLY when it is distance 1
    from exactly ONE fact token, shares that token's first 2 letters (typos
    rarely change a name's start), is NOT itself an exact fact token (another
    real player, e.g. Giménez next to Jiménez), and is not a common word."""
    fact_tokens = set()
    for ev in [*match.goals, *match.cards]:
        for tok in ev.player.split():
            if len(tok) >= 5:
                fact_tokens.add(_fold(tok))
    if not fact_tokens:
        return []
    issues = []
    seen = set()
    for word in re.findall(r"\b[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]{4,}\b", text):
        cand = _fold(word)
        if cand in fact_tokens or cand in seen or cand in _NOT_A_TYPO:
            continue                              # exact name / common word
        close = [ft for ft in fact_tokens
                 if cand[:2] == ft[:2] and _edit_distance(cand, ft, 1) <= 1]
        if len(close) == 1:                       # exactly one near match
            seen.add(cand)
            issues.append(f"'{word}' looks like a misspelling of a "
                          f"player name (closest fact: '{close[0]}')")
    return issues


# Proper nouns that are NOT people and legitimately appear mid-sentence without
# being in the match data: competition and country words the model may reach for
# when naming what it is describing. Everything else that looks like a name has
# to be traceable to the facts.
_KNOWN_PROPER = {
    "laliga", "liga", "champions", "europa", "conference", "eurocopa",
    "supercopa", "copa", "rey", "mundial", "espana", "uefa", "fifa",
    "primera", "segunda", "division", "hypermotion", "naciones", "jornada", "var",
}


def _fact_name_tokens(match: Match) -> set:
    """Every name-shaped word the match data actually contains.

    Drawn from the same material the model is given — teams, venue, city,
    country, competition, and every goal and card including their prose, which
    is where an assister's name lives. If a word is not in here, nothing told
    the model about it.
    """
    parts = [match.home, match.away, match.venue, match.city, match.country,
             match.competition]
    for ev in [*match.goals, *match.cards]:
        parts += [ev.player, ev.team, getattr(ev, "description", ""),
                  getattr(ev, "reason", "")]
    # The play-by-play notes matter as much as the goals: a disallowed goal or a
    # missed penalty names a player who appears NOWHERE else in the data, and the
    # narrator is expressly allowed to state those. Leaving them out flagged real
    # facts as inventions — "Brahim Díaz" for a VAR-overturned goal — on a third
    # of everything the channel had already published.
    parts += list(match.notes or [])
    parts += list((match.stats or {}).keys())
    tokens = set()
    for part in parts:
        for tok in re.findall(r"[^\W\d_]+", part or "", re.UNICODE):
            if len(tok) >= 3:
                tokens.add(_fold(tok))
    return tokens


def _invented_name_issues(match: Match, text: str) -> list[str]:
    """Flag a PERSON the match data never mentions.

    This exists because a real description published to the channel called Real
    Madrid "el equipo de Carlo Ancelotti" — a manager who left the club a season
    earlier. Nothing in a Match carries a coach at all, so that name could only
    have come from the model's training data, and no other layer could catch it:
    the deterministic checks verify what the data DOES state, and the free-prose
    invention they leave to the LLM judge is never run on a description.

    A stale fact stated with confidence is worse than a vague one, and a manager
    is exactly the kind of detail a model is sure about and wrong about.

    Deliberately narrow, because a false flag burns three regenerations: only
    words shaped like a name — initial capital, lower-case tail, so acronyms like
    VAR and LALIGA are never candidates — and never the first word of a sentence,
    which is capitalised by grammar rather than by being a name.
    """
    allowed = _fact_name_tokens(match)
    if not allowed:
        return []
    issues, seen = [], set()
    # Split on sentence boundaries and drop each sentence's opening word, whose
    # capital says nothing about whether it is a name.
    for sentence in re.split(r"(?<=[.!?\n])\s+", text):
        words = re.findall(r"\b[^\W\d_]+\b", sentence, re.UNICODE)
        for word in words[1:]:
            if not re.fullmatch(r"[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]{2,}", word):
                continue
            cand = _fold(word)
            if cand in allowed or cand in seen or cand in _KNOWN_PROPER:
                continue
            seen.add(cand)
            issues.append(f"'{word}' is a name the match data never mentions — "
                          f"do not name anyone who did not play, score or get "
                          f"booked, and never name a coach")
    return issues


# Football-noun genders for the determiner-agreement check. Spanish only.
# "área" is EXCLUDED: feminine but correctly takes "el/un" (stressed a-).
# "pase"/"remate" are EXCLUDED from this generic pattern: they are also verb
# forms that legitimately follow the clitic "la" (= la pelota), e.g. "para
# que la remate", "que se la pase" — valid historical-present recap prose.
# They get their own pattern below, guarded against those clitic readings.
_MASC_NOUNS = ("gol|golazo|penalti|penalty|penal|minuto|partido|balón|"
               "cabezazo|marcador|empate|resumen|estadio|encuentro|duelo|"
               "descuento|disparo|centro|córner|tiro|rincón|palo|"
               "triunfo|dominio|juego|portero|delantero|árbitro|equipo")
_FEM_NOUNS = ("tarjeta|amarilla|roja|cartulina|jugada|falta|asistencia|"
              "expulsión|portería|victoria|derrota|jornada|pelota|"
              "cancha|presión|banda|afición|ocasión|ventaja|goleada|"
              "remontada|amonestación|paliza")
_GENDER_SLIPS = (
    re.compile(rf"\b(?:la|una) (?:{_MASC_NOUNS})\b", re.IGNORECASE),
    re.compile(rf"\b(?:el|un|al|del) (?:{_FEM_NOUNS})\b", re.IGNORECASE),
    # "una pase"/"la remate final" are slips; "que/se la remate" is valid.
    re.compile(r"(?<!\bque )(?<!\bse )\b(?:una|la) (?:pase|remate)\b",
               re.IGNORECASE),
)


def _grammar_issues(text: str) -> list[str]:
    """Deterministic Spanish gender-agreement slips on football nouns:
    'la penalty', 'un tarjeta', 'la minuto'... The TTS reads these aloud."""
    issues = []
    for rx in _GENDER_SLIPS:
        for m in rx.finditer(text):
            issues.append(f"gender slip: '{m.group(0)}'")
    return issues


# ── Layer 1: deterministic facts check ───────────────────────────────
# Number words, for reading a score the narrator wrote out in full. The
# narrator SPELLS numbers on purpose — the text is fed to TTS, where "3-0" is
# read unpredictably and "tres a cero" is not — so "Termina dos a cero" is the
# expected shape of a final score, not an unusual one.
_NUM_WORDS = {
    # Spanish
    "cero": 0, "uno": 1, "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12,
    # English
    "zero": 0, "nil": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
}

# Only ever rewrite a number word sitting in a SCORE-SHAPED pair. Substituting
# every "un" in Spanish prose would turn "un disparo" into "1 disparo" and
# manufacture score tokens that were never there — a false pass, which is far
# worse than the false failure this fixes.
_SCORE_PAIR_RE = re.compile(
    rf"\b({'|'.join(sorted(_NUM_WORDS, key=len, reverse=True))}|\d{{1,2}})"
    rf"\s*(?:[-:x]|\s(?:a|to)\s)\s*"
    rf"({'|'.join(sorted(_NUM_WORDS, key=len, reverse=True))}|\d{{1,2}})\b",
    re.IGNORECASE,
)


def _digitise_scores(text: str) -> str:
    """Rewrite word-form scores ("dos a cero") as digits ("2-0") so the score
    checks below see them. Digits already present are left untouched."""
    def one(m):
        a, b = m.group(1).lower(), m.group(2).lower()
        a = _NUM_WORDS.get(a, a)
        b = _NUM_WORDS.get(b, b)
        return f"{a}-{b}"
    return _SCORE_PAIR_RE.sub(one, text)


# Words that sit INSIDE a club's name in running prose without identifying it.
# Only words of 4+ characters ever become team tokens, so this list just has to
# cover the connectors and legal-form words a narrator writes between the parts
# of a name ("Racing DE Santander", "EL Alaves").
# Deliberately NOT here: "Sociedad", "Deportivo", "Sporting". They look generic
# but they are the only distinctive word in Real Sociedad, Deportivo and
# Sporting de Gijon — filtering them leaves those clubs with no token at all.
_TEAM_FILLER = frozenset({
    "de", "del", "la", "el", "los", "las", "y", "e",
    "club", "futbol", "football",
    "fc", "cf", "cd", "ud", "sd", "rc", "rcd", "ca", "sad",
})


def _team_anchored_scores(match: Match, folded: str) -> list[tuple[int, tuple, str]]:
    """(position, sorted pair, as-written) for a score with the TEAM NAMES
    BETWEEN the digits: "Racing de Santander 2, Alaves 1".

    The adjacent-token regex cannot see this form — it needs the two numbers on
    either side of ONE separator, and here a whole club name is in the way. That
    is not an exotic phrasing, it is how a Spanish commentator reads a full-time
    score aloud, and it held a correct Racing 2-1 Alaves recap off the channel:
    the deterministic check reported the final score was "not clearly stated"
    while the LLM judge, reading the very same sentence, called it grounded.

    Anchoring each number to a REAL team name is what keeps this from becoming
    dangerous. Pairing bare digits a few words apart would manufacture scores
    out of minutes and percentages ("al 62 ... un 57 por ciento") and turn a
    false failure into a false PASS, which is the far worse direction here.
    """
    def tokens(name: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", _fold(name))
                if len(t) >= 4 and t not in _TEAM_FILLER}

    home_t, away_t = tokens(match.home), tokens(match.away)
    # A token the two sides SHARE identifies neither of them (Real Madrid vs
    # Real Sociedad, Athletic vs Atletico), so it anchors nothing.
    shared = home_t & away_t
    home_t, away_t = home_t - shared, away_t - shared
    if not home_t or not away_t:
        return []

    anchored = []                      # (position, side, number)
    for m in re.finditer(r"\b(\d{1,2})\b", folded):
        # Walk backwards over the words immediately before the number, stepping
        # through the filler a club name carries, and stop at the first word
        # that belongs to neither name.
        side = None
        for w in reversed(re.findall(r"[a-z0-9]+",
                                     folded[max(0, m.start() - 40):m.start()])):
            if w in home_t or w in away_t:
                this = "home" if w in home_t else "away"
                if side and this != side:
                    side = None        # both clubs in one run — ambiguous
                    break
                side = this
            elif w in _TEAM_FILLER:
                continue
            else:
                break
        if side:
            anchored.append((m.start(), side, int(m.group(1))))

    # Two anchored numbers in a row, one per side and close enough together to
    # be one scoreline rather than two sentences that each mention a club.
    pairs = []
    for (p1, s1, n1), (p2, s2, n2) in zip(anchored, anchored[1:], strict=False):
        if s1 != s2 and p2 - p1 <= 60:
            pairs.append((p2, tuple(sorted((n1, n2))), f"{n1}-{n2}"))
    return pairs


# ── Language enforcement ─────────────────────────────────────────────
# A Chinese description was once published under a Spanish title: the fallback
# chain reached qwen, a Chinese-trained model, and nothing checked the language
# because the metadata path runs the facts layer WITHOUT the LLM judge for cost.
# So this must stay deterministic — an LLM check would not protect that path,
# and could itself fail over to a model answering in the wrong language.
#
# Two independent tests, because they catch different drifts:
#   · the WRITING SYSTEM, which catches Chinese, Cyrillic, Arabic and friends
#   · Spanish FUNCTION WORDS, which catch the far likelier drift into English
#     or another Latin-script language, invisible to a script check
_NON_LATIN_RANGES = (
    (0x0370, 0x03FF), (0x0400, 0x052F),          # Greek, Cyrillic (+ supplement)
    (0x0530, 0x058F), (0x0590, 0x05FF),          # Armenian, Hebrew
    (0x0600, 0x06FF), (0x0700, 0x074F),          # Arabic, Syriac
    (0x0780, 0x07BF), (0x0900, 0x0DFF),          # Thaana, all Indic scripts
    (0x0E00, 0x0EFF), (0x0F00, 0x0FFF),          # Thai/Lao, Tibetan
    (0x1000, 0x109F), (0x10A0, 0x10FF),          # Myanmar, Georgian
    (0x1200, 0x139F), (0x13A0, 0x13FF),          # Ethiopic, Cherokee
    (0x1780, 0x17FF), (0x1800, 0x18AF),          # Khmer, Mongolian
    (0x1F00, 0x1FFF),                            # Greek Extended
    (0x2E80, 0x2FDF),                            # CJK + Kangxi radicals
    (0x3000, 0x303F), (0x3040, 0x30FF),          # CJK punctuation, kana
    (0x3100, 0x312F), (0x3130, 0x318F),          # Bopomofo, Hangul jamo
    (0x1100, 0x11FF),                            # Hangul jamo (what NFD produces)
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF),          # CJK ideographs
    (0xA000, 0xA4CF),                            # Yi
    (0xAC00, 0xD7AF),                            # Hangul syllables
    (0xF900, 0xFAFF),                            # CJK compatibility
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),          # Arabic presentation forms
    (0xFF00, 0xFFDC),                            # Fullwidth AND halfwidth kana
    (0x20000, 0x3FFFF),                          # CJK extensions B and beyond
)

# Latin-script languages this project generates.
_LATIN_LANGS = {"es", "en", "fr", "it", "pt", "de", "ca", "gl", "eu",
                "nl", "sv", "da", "no", "pl", "ro", "cs", "hu", "tr"}

# Spellings of a language that mean the same thing. Without this, a profile or
# an API caller writing "es-ES" instead of "es" turned the whole guard off — it
# fell through to "unknown language, do not guess" and returned clean.
_LANG_ALIASES = {"spa": "es", "spanish": "es", "castellano": "es", "cast": "es",
                 "eng": "en", "english": "en", "fra": "fr", "french": "fr",
                 "ita": "it", "italian": "it", "por": "pt", "portuguese": "pt"}


def _base_lang(language: str) -> str:
    """Normalise a language tag to its base subtag: es-ES, es_419, Spanish -> es."""
    raw = (language or "es").strip().lower().replace("_", "-")
    raw = raw.split("-")[0]
    return _LANG_ALIASES.get(raw, raw)


# Function words are the honest signal for language identity: they are frequent,
# closed-class and survive any subject matter, unlike the proper nouns that
# dominate a football recap and look identical in every language.
_MARKERS = {
    "es": {"el", "la", "los", "las", "de", "del", "que", "en", "con", "por",
           "para", "un", "una", "y", "se", "su", "al", "lo", "es", "pero",
           "como", "mas", "más", "sin", "sobre", "desde", "cuando", "tras"},
    "en": {"the", "of", "and", "to", "in", "with", "for", "was", "were", "his",
           "their", "from", "after", "which", "that", "this", "have", "has"},
    "pt": {"o", "os", "as", "do", "da", "dos", "das", "que", "em", "com", "para",
           "uma", "não", "mas", "seu", "pelo", "pela"},
    "it": {"il", "lo", "gli", "della", "che", "con", "per", "una", "sono",
           "nel", "dal", "suo", "anche", "dopo"},
    "fr": {"le", "les", "des", "du", "que", "dans", "avec", "pour", "une",
           "est", "sur", "par", "ses", "mais", "cette"},
}

_WORD_RE = re.compile(r"[a-záéíóúüñàèìòùâêîôûçãõäöß]+", re.IGNORECASE)


def _wrong_script(text: str, language: str) -> str:
    """Characters from a writing system the target language never uses.

    A THRESHOLD applies rather than firing on the first character: a Spanish
    recap may legitimately gloss a club or a player in its own script ("el
    Ολυμπιακός", "Артем Довбик"), and this profile covers a Japanese-named club.
    Failing those costs three regeneration attempts and ships the draft anyway,
    so a handful of foreign characters inside otherwise-Spanish prose is treated
    as a quotation, while a text actually written in another script is not.
    """
    lang = _base_lang(language)
    if lang not in _LATIN_LANGS:
        return ""              # no script rules for this target; do not guess
    bad = [ch for ch in (text or "")
           if any(lo <= ord(ch) <= hi for lo, hi in _NON_LATIN_RANGES)]
    if not bad:
        return ""
    # Quotation, or genuinely another script? Judge by PROPORTION, not by a raw
    # count: a club name glossed natively runs about ten characters ("el
    # Ολυμπιακός"), which a small fixed threshold rejects, while text actually
    # written in another script is overwhelmingly made of it. A long foreign
    # passage inside a long text is caught by the absolute arm.
    ratio = len(bad) / max(len(text or ""), 1)
    if ratio < 0.15 and len(bad) < 40:
        return ""
    return "".join(dict.fromkeys(bad))[:12]


def _wrong_latin_language(text: str, language: str) -> str:
    """The Latin-script language `text` looks like, when it is not `language`.

    This is the drift a script check cannot see, and the likelier one: the
    fallback chain is full of English-biased models, so a Spanish instruction is
    far more often answered in English than in Chinese. Deliberately conservative
    — it only speaks up when the target's own function words are nearly absent
    AND another language's clearly dominate, so a Spanish sentence quoting an
    English phrase never trips it.
    """
    lang = _base_lang(language)
    if lang not in _MARKERS:
        return ""
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    if len(words) < 25:
        return ""              # too short to judge; a title is not evidence
    counts = {code: sum(w in marks for w in words)
              for code, marks in _MARKERS.items()}
    own = counts[lang]
    rival, rival_n = max(((c, n) for c, n in counts.items() if c != lang),
                         key=lambda kv: kv[1])
    own_ratio = own / len(words)
    # Spanish prose runs well over 15% function words. Requiring the target to
    # be under 4% AND a rival to more than double it keeps this far away from
    # any real Spanish text.
    if own_ratio < 0.04 and rival_n >= max(4, own * 2 + 2):
        return rival
    return ""


def facts_check(match: Match, text: str, language: str = "es", *,
                ordered_score: bool = True) -> dict:
    """Cheap, deterministic verification against the raw match data.

    `ordered_score`: when True (a play-by-play narration), the LAST score-shaped
    token must be the final. Set False for YouTube title+description, where the
    title carries the final FIRST and the description may recount a running
    score ('se adelantó 1-0') last — there the 'last token = final' rule would
    false-fail. The 'final must appear at least once' rule still applies."""
    issues = []

    # Language first: the parameter was accepted here and never used, so a
    # description generated in the wrong writing system passed every other check
    # (the scores and names it quoted were correct) and was published.
    wrong = _wrong_script(text, language)
    if wrong:
        issues.append(f"text is not written in {language} "
                      f"(found non-Latin characters: {wrong})")
    else:
        other = _wrong_latin_language(text, language)
        if other:
            issues.append(f"text reads as '{other}', not {language}")

    # Verify the FINAL score. A play-by-play narration states running scores as
    # it goes, so "the correct pair appears somewhere" is not enough — a wrong
    # invented final could slip past while a true running score matches. So we
    # check the LAST score-shaped token in the text equals the real final, and
    # that no OTHER score appears in a full-time context.
    # Normalise unicode dashes (‑ – —) to a plain hyphen first.
    norm = text.translate({0x2010: "-", 0x2011: "-", 0x2012: "-",
                           0x2013: "-", 0x2014: "-", 0x2212: "-"})
    norm = _digitise_scores(norm)
    h, a = match.home_goals, match.away_goals
    # A goalless draw is narrated as "empate sin goles" far more often than as a
    # literal "0-0", so the score-token check would false-fail almost every real
    # 0-0 narration. Only enforce the token when at least one goal was scored.
    if h is not None and a is not None and (h or a):
        sep = r"\s*(?:[-:x]|\s(?:a|to)\s)\s*"
        score_re = re.compile(rf"\b(\d{{1,2}}){sep}(\d{{1,2}})\b")
        # A sorted PAIR, not a set: order-agnostic either way, but a set
        # collapses a draw to a single element and then reports a 1-1 as
        # 'the last score stated (1)', which reads like a bug to the human the
        # hold is asking to review it.
        target = tuple(sorted((h, a)))         # order-agnostic final score
        # Both scans run over the SAME folded text so their positions are
        # comparable: "2-1" and "Racing 2, Alaves 1" are the same statement
        # written two ways and have to be ordered against each other.
        folded = _fold(norm)
        # Each hit carries how it was WRITTEN as well as the order-agnostic
        # pair, so the message a human reads quotes the text back to them
        # ("the last score stated (0-1)") instead of a re-sorted version of it.
        found = [(m.start(), tuple(sorted((int(m.group(1)), int(m.group(2))))),
                  f"{m.group(1)}-{m.group(2)}")
                 for m in score_re.finditer(folded)]
        found += _team_anchored_scores(match, folded)
        pairs = sorted(found, key=lambda t: t[0])
        final_str = f"{h}-{a}"                 # as it was actually played

        # 1) The correct final must appear at least once.
        if target not in [pair for _, pair, _w in pairs]:
            issues.append(f"final score {h}-{a} not clearly stated")
        # 2) The LAST score-shaped token that equals a PLAUSIBLE football score
        #    must be the final. Football prose freely contains minute ranges
        #    ("los 90-95 minutos", "el 10-15"), so we ignore trailing pairs whose
        #    numbers are both too large to be a scoreline (>9) before deciding —
        #    otherwise a legitimate range after the score would false-fail.
        elif ordered_score:
            scorelike = [(pair, written) for _, pair, written in pairs
                         if all(x <= 9 for x in pair)]
            if scorelike and scorelike[-1][0] != target:
                issues.append(f"the last score stated ({scorelike[-1][1]}) "
                              f"is not the final {final_str}")

    # Everything the data states exactly IS checked exactly. Each of these
    # caught (or would have caught) a real shipped mistake: a red card narrated
    # as yellow, a right-footed goal described as 'de zurda', 'César Montaes'.
    issues += _card_color_issues(match, norm)
    issues += _goal_detail_issues(match, norm)
    issues += _goal_type_issues(match, norm)
    issues += _name_spelling_issues(match, text)
    issues += _invented_name_issues(match, text)
    if (language or "es").startswith("es"):
        issues += _grammar_issues(norm)

    # Free-prose invention beyond these (a player neither scoring nor carded,
    # invented causes) is left to the LLM-judge layer below.
    return {"ok": not issues, "issues": issues}


# ── Layer 2: LLM-as-judge ────────────────────────────────────────────
_JUDGE_SYS = (
    "You are a strict fact-checking judge. Given the MATCH FACTS and a generated "
    "NARRATION, decide if the narration is grounded in the facts (no invented "
    "scores, scorers, minutes; every card keeps its EXACT colour from the facts — "
    "a red card narrated as yellow, or yellow as red, is NOT grounded; every goal "
    "keeps its exact type — penalty and own goal must be narrated as such — and "
    "its body part: a header never becomes a shot, a right foot never becomes a "
    "left foot, and no body part may be invented), is written "
    "in the expected LANGUAGE, and stays respectful.\n"
    # Without this, the judge reads "grounded" as "complete" and rejects correct
    # prose for what it leaves out. That is the wrong test twice over: a digest
    # segment is a ~20-second condensation that CANNOT list nine bookings, and
    # even a full reel is edited, not a transcript. Judging omission here burned
    # all three regeneration attempts on narrations that invented nothing, and
    # shipped them flagged anyway. Completeness is the narrator prompt's job;
    # this layer exists to catch fabrication and contradiction.
    "IMPORTANT: the narration is an edited summary, not a transcript. Leaving an "
    "event out is NOT a grounding failure — judge ONLY what the narration "
    "actually asserts. Mark grounded=false only when it states something the "
    "facts contradict or never mention. Never mark it false for being "
    "incomplete, condensed, or for omitting cards, goals or statistics.\n"
    "Respond as JSON only: "
    '{"grounded": bool, "language_ok": bool, "tone_ok": bool, "reason": str}.'
)


# The judge runs on a REASONING model, which spends tokens thinking before it
# answers. 300 was enough for the older non-reasoning judge but truncates a
# reasoning one mid-thought: the completion then carries no `content`, the LLM
# wrapper falls back to the `reasoning` text, and the judge "fails to parse" on
# every single call — silently disabling this whole layer while `verify()` keeps
# passing narrations on the facts check alone. The budget must clear the
# reasoning plus the verdict.
_JUDGE_MAX_TOKENS = 1200

# Some models wrap their thinking in <think>…</think> and then answer; others
# print prose and end with the JSON. Strip the think block, then take the LAST
# balanced {...} — the last one is the verdict, since anything the model quotes
# while reasoning comes earlier.
_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.S | re.I)


def _extract_json(raw: str) -> str:
    """Pull the verdict object out of a reasoning model's reply."""
    cleaned = _THINK_RE.sub(" ", raw or "").strip()
    start, depth = None, 0
    best = ""
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                best = cleaned[start:i + 1]      # keep the last complete object
    return best or cleaned


def llm_judge(match: Match, text: str, language: str, *, provider: str | None = None,
              model: str | None = None) -> dict:
    from pipeline.narrator import _facts_block

    user = (
        f"MATCH FACTS:\n{_facts_block(match)}\n\n"
        f"EXPECTED LANGUAGE: {language}\n\n"
        f"NARRATION:\n{text}"
    )
    raw = call_llm(
        [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": user}],
        provider=provider, model=model, max_tokens=_JUDGE_MAX_TOKENS,
        label="Guardrail",
    )
    try:
        data = json.loads(repair_json(_extract_json(raw)))
        if not isinstance(data, dict) or "grounded" not in data:
            raise ValueError("judge returned no usable verdict")
    except Exception as e:
        # Unparseable judge output must NOT fail closed: a judge model that
        # answers in prose would otherwise flag every clean narration and burn
        # the whole retry budget. Signal "unknown" so verify() falls back to
        # the deterministic facts layer, exactly like a transport error does.
        return {"parsed": False, "error": str(e)}
    return {
        "parsed": True,
        "grounded": bool(data.get("grounded", False)),
        "language_ok": bool(data.get("language_ok", False)),
        "tone_ok": bool(data.get("tone_ok", True)),
        "reason": data.get("reason", "no reason returned"),
    }


def verify(match: Match, text: str, language: str, *,
           judge_provider: str | None = None, judge_model: str | None = None,
           use_judge: bool = True) -> dict:
    """Combined verdict. `passed` is True only if both layers agree.

    When the judge is unreachable OR returns unparseable output, we fall back
    to the deterministic facts layer (fail-open on the judge) rather than
    blocking a clean narration on a flaky judge model."""
    facts = facts_check(match, text, language)
    result = {"facts": facts, "passed": facts["ok"]}
    if use_judge:
        try:
            judge = llm_judge(match, text, language, provider=judge_provider,
                              model=judge_model)
            result["judge"] = judge
            if judge.get("parsed"):
                result["passed"] = (facts["ok"] and judge["grounded"]
                                    and judge["language_ok"])
            # else: judge unusable -> keep facts-only verdict (already set)
        except Exception as e:  # noqa: BLE001
            result["judge"] = {"error": str(e)}
    return result
