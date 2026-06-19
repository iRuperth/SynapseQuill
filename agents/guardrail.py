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


# Words that signal each card colour in the narration (Spanish + English).
# "amonest·ó/ado/ación" + "booked/caution" imply yellow; "expuls·ado/ión" /
# "sent off" / "roja" imply red. Deliberately NO bare "red" (matches Spanish
# "la red", the net). "roja" needs both boundaries (the surname "Rojas") AND a
# guard against "la roja" (Spain's nickname) — handled in _card_color_issues,
# not here, because the nickname only matters next to a Spain player's name.
_CARD_WORDS = {
    "Yellow": re.compile(r"\bamarilla|yellow|\bamonest|\bbooked\b|\bbooking\b|"
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
        saw_wrong_only = saw_right = False
        for s, e in _name_windows(player, folded):
            window = folded[max(0, s - 90): e + 90]
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
    "right": re.compile(r"\bderechazo|\bdiestra\b|pierna derecha|"
                        r"con (?:la|su) derecha|de derecha\b(?! a izquierda)",
                        re.IGNORECASE),
    "left": re.compile(r"\bzurd|pierna izquierda|"
                       r"con (?:la|su) izquierda|de izquierda\b(?! a derecha)",
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
        saw_wrong_only = saw_right = False
        for s, e in _name_windows(g.player, folded):
            window = folded[max(0, s - 90): e + 90]
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
    has_pen = any("Pen" in (g.kind or "") for g in match.goals)
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
def facts_check(match: Match, text: str, language: str = "es", *,
                ordered_score: bool = True) -> dict:
    """Cheap, deterministic verification against the raw match data.

    `ordered_score`: when True (a play-by-play narration), the LAST score-shaped
    token must be the final. Set False for YouTube title+description, where the
    title carries the final FIRST and the description may recount a running
    score ('se adelantó 1-0') last — there the 'last token = final' rule would
    false-fail. The 'final must appear at least once' rule still applies."""
    issues = []

    # Verify the FINAL score. A play-by-play narration states running scores as
    # it goes, so "the correct pair appears somewhere" is not enough — a wrong
    # invented final could slip past while a true running score matches. So we
    # check the LAST score-shaped token in the text equals the real final, and
    # that no OTHER score appears in a full-time context.
    # Normalise unicode dashes (‑ – —) to a plain hyphen first.
    norm = text.translate({0x2010: "-", 0x2011: "-", 0x2012: "-",
                           0x2013: "-", 0x2014: "-", 0x2212: "-"})
    h, a = match.home_goals, match.away_goals
    # A goalless draw is narrated as "empate sin goles" far more often than as a
    # literal "0-0", so the score-token check would false-fail almost every real
    # 0-0 narration. Only enforce the token when at least one goal was scored.
    if h is not None and a is not None and (h or a):
        sep = r"\s*(?:[-:x]|\s(?:a|to)\s)\s*"
        score_re = re.compile(rf"\b(\d{{1,2}}){sep}(\d{{1,2}})\b")
        target = frozenset((h, a))             # order-agnostic final score
        pairs = [frozenset((int(m1), int(m2))) for m1, m2 in score_re.findall(norm)]
        final_str = "-".join(str(x) for x in sorted((h, a)))

        # 1) The correct final must appear at least once.
        if target not in pairs:
            issues.append(f"final score {h}-{a} not clearly stated")
        # 2) The LAST score-shaped token that equals a PLAUSIBLE football score
        #    must be the final. Football prose freely contains minute ranges
        #    ("los 90-95 minutos", "el 10-15"), so we ignore trailing pairs whose
        #    numbers are both too large to be a scoreline (>9) before deciding —
        #    otherwise a legitimate range after the score would false-fail.
        elif ordered_score:
            scorelike = [p for p in pairs if all(x <= 9 for x in p)]
            if scorelike and scorelike[-1] != target:
                stated = "-".join(str(x) for x in sorted(scorelike[-1]))
                issues.append(f"the last score stated ({stated}) is not the final {final_str}")

    # Everything the data states exactly IS checked exactly. Each of these
    # caught (or would have caught) a real shipped mistake: a red card narrated
    # as yellow, a right-footed goal described as 'de zurda', 'César Montaes'.
    issues += _card_color_issues(match, norm)
    issues += _goal_detail_issues(match, norm)
    issues += _goal_type_issues(match, norm)
    issues += _name_spelling_issues(match, text)
    if (language or "es").startswith("es"):
        issues += _grammar_issues(norm)

    # Free-prose invention beyond these (a player neither scoring nor carded,
    # invented causes) is left to the LLM-judge layer below.
    return {"ok": not issues, "issues": issues}


# ── Layer 2: LLM-as-judge ────────────────────────────────────────────
_JUDGE_SYS = (
    "You are a strict fact-checking judge. Given the MATCH FACTS and a generated "
    "NARRATION, decide if the narration is fully grounded in the facts (no invented "
    "scores, scorers, minutes; every card keeps its EXACT colour from the facts — "
    "a red card narrated as yellow, or yellow as red, is NOT grounded; every goal "
    "keeps its exact type — penalty and own goal must be narrated as such — and "
    "its body part: a header never becomes a shot, a right foot never becomes a "
    "left foot, and no body part may be invented), is written "
    "in the expected LANGUAGE, and stays respectful. Respond as JSON only: "
    '{"grounded": bool, "language_ok": bool, "tone_ok": bool, "reason": str}.'
)


def llm_judge(match: Match, text: str, language: str, *, provider: str | None = None) -> dict:
    from pipeline.narrator import _facts_block

    user = (
        f"MATCH FACTS:\n{_facts_block(match)}\n\n"
        f"EXPECTED LANGUAGE: {language}\n\n"
        f"NARRATION:\n{text}"
    )
    raw = call_llm(
        [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": user}],
        provider=provider, max_tokens=300, label="Guardrail",
    )
    try:
        data = json.loads(repair_json(raw))
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
           judge_provider: str | None = None, use_judge: bool = True) -> dict:
    """Combined verdict. `passed` is True only if both layers agree.

    When the judge is unreachable OR returns unparseable output, we fall back
    to the deterministic facts layer (fail-open on the judge) rather than
    blocking a clean narration on a flaky judge model."""
    facts = facts_check(match, text, language)
    result = {"facts": facts, "passed": facts["ok"]}
    if use_judge:
        try:
            judge = llm_judge(match, text, language, provider=judge_provider)
            result["judge"] = judge
            if judge.get("parsed"):
                result["passed"] = (facts["ok"] and judge["grounded"]
                                    and judge["language_ok"])
            # else: judge unusable -> keep facts-only verdict (already set)
        except Exception as e:  # noqa: BLE001
            result["judge"] = {"error": str(e)}
    return result
