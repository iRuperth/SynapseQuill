"""
narrator.py — turn raw match data into an exciting broadcaster narration.

The LLM is given ONLY the factual match data (teams, score, scorers, minutes)
plus the profile's system_preamble (brand/persona). It must never invent
scores or scorers — that is enforced downstream by the guardrail (expert level).

Multi-language: ES / EN / FR / IT, selected by the profile language.
"""

from core.llm import call_llm

from .match_monitor import Match

_LANG_NAME = {
    "es": "Spanish", "en": "English", "fr": "French", "it": "Italian",
}


def _goal_min(s) -> int:
    """Parse a goal minute like '23' or '90+4' to an int for ordering."""
    try:
        return int(str(s).split("+")[0])
    except (ValueError, TypeError):
        return 999


def _was_comeback(match: Match) -> bool:
    """True if the team that WON the match was behind on the scoreboard at some
    point — i.e. it came from behind to win. Walks the goals in chronological
    order, tracking the running score. Needs goal events; returns False if the
    final result is a draw or the play-by-play is missing."""
    winner = match.winner
    if not winner or not match.goals:
        return False
    hg = ag = 0
    for g in sorted(match.goals, key=lambda x: _goal_min(x.minute)):
        # The event's team is the SCORER's team; an own goal credits the
        # OPPOSING side, so flip it in that case.
        own = "Own" in (g.kind or "")
        if own:
            scoring_side = match.away if g.team == match.home else match.home
        else:
            scoring_side = g.team
        if scoring_side == match.home:
            hg += 1
        elif scoring_side == match.away:
            ag += 1
        # Was the eventual winner trailing right now?
        if winner == match.home and hg < ag:
            return True
        if winner == match.away and ag < hg:
            return True
    return False


def describe_match(match: Match) -> str | None:
    """A short, NEUTRAL description of the match's character, to guide the
    narration's tone. Returns an English guidance string (the other facts are in
    English too) or None when the score is unknown.

    The wording is deliberately respectful — never humiliating. The LLM is asked
    to convey this character in its own varied words, so we describe the SHAPE of
    the result, not a fixed phrase to copy.
    """
    h, a = match.home_goals, match.away_goals
    if h is None or a is None:
        return None
    diff = abs(h - a)
    # A shootout means it was level after normal/extra time, even though there
    # is a winner. Treat that as a draw-in-play, not a clear win.
    pen = match.went_to_penalties or match.status == "PEN"
    draw = (h == a) and not pen

    parts = []
    if pen:
        winner = match.winner
        tail = (f" {winner} advanced." if winner else "")
        parts.append(
            "Very evenly matched — it stayed level and was settled on a penalty "
            f"shootout.{tail} Convey the tension and that both teams deserved "
            "credit.")
    elif draw:
        parts.append(
            "A balanced, evenly-contested match that ended in a draw. "
            "Convey the parity between the two sides.")
    elif diff >= 6:
        parts.append(
            "A dominant, one-sided win for the winner. Convey command and "
            "authority RESPECTFULLY — celebrate the winner's level, never mock "
            "or humiliate the losing side.")
    elif diff >= 2:
        parts.append(
            "A clear, comfortable win for the winner — they controlled the game "
            "and took the result with authority.")
    else:  # diff == 1
        parts.append(
            "A tight, closely-fought match decided by the finest margin. "
            "Convey how hard-fought and competitive it was.")

    # A comeback only counts when the game was WON on goals (the winner was
    # behind and overturned it). A level game decided on penalties is not a
    # comeback even though there is a winner.
    if diff > 0 and not pen and _was_comeback(match):
        parts.append(
            f"It was a COMEBACK: {match.winner} fell behind and turned it around "
            "to win. Emphasise the fightback and character to recover.")

    return " ".join(parts)


def _facts_block(match: Match) -> str:
    """Build a compact, unambiguous factual summary for the LLM."""
    lines = []
    if match.competition:
        lines.append(f"Competition: {match.competition}")
    if match.date:
        lines.append(f"Date: {match.date}")
    lines += [
        f"Home team: {match.home}",
        f"Away team: {match.away}",
        f"Final score: {match.home} {match.home_goals} - {match.away_goals} {match.away}",
    ]
    # Tone guidance from the result's shape (blowout / close / draw / penalties /
    # comeback). The model conveys this in its own respectful words.
    character = describe_match(match)
    if character:
        lines.append(f"Match character (use this tone, in your own words, "
                     f"respectfully): {character}")
    if match.venue:
        lines.append(f"Venue: {match.venue}")
    # Build ONE chronological list of every event (goals AND cards together),
    # so the narration can run through the match minute by minute.
    events = []
    for g in match.goals:
        kind = "penalty goal" if "Pen" in g.kind else (
            "own goal" if "Own" in g.kind else "goal")
        line = f"minute {g.minute}: {kind} for {g.team}, scored by {g.player}"
        if g.description:
            line += f" — {g.description}"
        events.append((_goal_min(g.minute), line))
    for c in match.cards:
        events.append((_goal_min(c.minute),
                       f"minute {c.minute}: {c.color} card for {c.player} of {c.team}"))

    if events:
        events.sort(key=lambda e: e[0])
        lines.append("Match events in chronological order (narrate ALL of them, in this order):")
        for _, line in events:
            lines.append(f"  - {line}")
    else:
        lines.append("No goals or cards (0-0).")
    return "\n".join(lines)


# Word-length guidance per narration style.
_LENGTH = {
    "full": "110-170 words, including the opening presentation and the closing "
            "call to action.",
    "digest_short": "VERY SHORT: 30-45 words MAXIMUM — this is one match in a fast daily "
                    "digest. One punchy line on the result and the key goal(s). Do not list "
                    "every detail.",
    "digest_long": "150-220 words with more detail and context — this is one match in a "
                   "longer YouTube digest.",
}


def narrate(match: Match, *, language: str = "es", system_preamble: str = "",
            provider: str | None = None, style: str = "full") -> str:
    """Return an exciting narration script for `match`.

    style: full (single-match reel) | digest_short (~20s segment) |
    digest_long (detailed YouTube segment).
    """
    lang = _LANG_NAME.get(language, "Spanish")
    length = _LENGTH.get(style, _LENGTH["full"])

    # A single-match reel (style "full") opens by presenting the match and closes
    # by inviting viewers to follow + like. The fast daily digest (very short
    # per-match segments) skips this so each segment stays punchy.
    if style == "full":
        intro_outro = (
            "- START by presenting the match in your own words, naming BOTH teams, "
            "like the opening of a highlights recap (e.g. 'Bienvenidos al resumen "
            "del partidazo entre X e Y' / 'Esto fue lo que pasó en el duelo entre "
            "X e Y'). Vary the wording, keep it short and electric.\n"
            "- FINISH, after the epic closing line, with a short, natural call to "
            "action inviting viewers to FOLLOW the channel and leave a LIKE for "
            "more highlights (e.g. 'si lo viviste con nosotros, síguenos y deja tu "
            "like para más resúmenes'). Make it sound genuine, never spammy, and "
            "vary it every time.\n"
        )
    else:
        intro_outro = ""

    system = (system_preamble + "\n\n" if system_preamble else "") + (
        f"You are a LEGENDARY, white-hot football play-by-play commentator. Write ONLY in {lang}. "
        "Narrate like a live radio announcer whose heart is about to burst — MAXIMUM passion, "
        "drama and emotion in every line:\n"
        f"{intro_outro}"
        "- Open with a gripping hook that sells the drama of the result in one breath.\n"
        "- Short, explosive, breathless sentences. Build unbearable tension before each goal, "
        "then EXPLODE. Vary the rhythm: whisper the build-up, scream the goal.\n"
        "- Pour in raw emotion and vivid, visceral imagery — the roar of the crowd, nerves of "
        "steel, hearts pounding, the net rippling — but NEVER invent facts to do it.\n"
        "- Use interjections on goals "
        "(in Spanish: '¡GOOOL!', '¡QUÉ GOOOLAZO!', '¡INCREÍBLE!', '¡DE LOCURA!', '¡IMPARABLE!'; "
        "in English: 'GOOOAL!', 'WHAT A STRIKE!', 'UNBELIEVABLE!'). "
        "Stretch the cheer to EXACTLY 3 repeated vowels — 'GOOOL', 'GOOOLAZO' (three O's), "
        "never more than 3 (not 'GOOOOOL'), because the voice reads too many vowels as 'Go-ol'.\n"
        "- CRITICAL — make goals FLOW: connect the play and the goal in ONE continuous "
        "sentence using a linking verb, never leave a bare '¡Gol!' dangling on its own after "
        "a full stop. WRONG (choppy): 'remata con la izquierda. ¡Gol!'. RIGHT (fluid): "
        "'remata con la izquierda y MARCA el gol', '...y la manda al fondo, ¡GOOOL!', "
        "'...y anota', '...para el GOOOLAZO', '...y la clava en la red'. The cheer "
        "('¡GOOOL!') should ride the SAME breath as the action, joined by 'y'/'para'/a "
        "comma — the action and the goal are one motion, not two separate lines.\n"
        "- Put the most intense words in CAPITALS for emphasis.\n"
        "- When 'how it happened' is given for a goal, describe the play vividly using it.\n"
        "- Go through the match EVENT BY EVENT in the given chronological order, narrating "
        "EVERY card AND every goal as they happen. Do not skip cards.\n"
        "- Narrate cards like a HUMAN commentator, never as a data line. NEVER say "
        "'minuto 7, Buba Sangaré, tarjeta' — that sounds like a robot reading a log. "
        "Instead make the player the subject of an ACTION and vary the verb every time: "
        "'al minuto 7 Buba Sangaré se gana la primera amarilla del partido', "
        "'ve la cartulina amarilla', 'el árbitro le muestra la amarilla', "
        "'es amonestado', 'se lleva una tarjeta'. For a RED card raise the drama: "
        "'roja directa, ¡y se queda con uno menos!', 'expulsado, deja a los suyos en "
        "inferioridad'. CRITICAL: do NOT invent WHY the card was shown — you are NOT "
        "told the reason, so never add a cause like 'tras una dura entrada', 'por "
        "protestar' or 'por falta'. Only state who, the team, the colour and the minute. "
        "For the FIRST card of the match say so ('la primera amarilla del encuentro'). "
        "Announce the minute naturally ('al minuto 7', 'hacia la media hora', 'ya en el "
        "60') — never bare 'minuto 7'. Mix these forms so no two cards sound the same "
        "and it never reads as a list.\n"
        "- NEVER read team names in parentheses. Say them naturally — e.g. "
        "'gol del Girona, obra de Germán Martínez' or 'amarilla para Casemiro, del Real Madrid', "
        "never 'Germán Martínez (Girona)'.\n"
        "- Write FLAWLESS, natural Spanish grammar. Watch gender/agreement on "
        "football words: 'penalti'/'penalty'/'penal' are MASCULINE — say 'el "
        "penalti', 'un penalti', 'convierte el penalti', NEVER 'la penalty'. "
        "Use 'del'/'al', never 'de el'/'a el'.\n"
        "- When you name the stadium, refer to it naturally as 'el estadio <name>' or keep its "
        "article — say 'en el estadio de la Cerámica' or 'en La Cerámica', NEVER a bare "
        "'en la Cerámica' that reads as an adjective. Mentioning the stadium is optional; only "
        "do it if it flows.\n"
        "- End with an EPIC, goosebumps closing line that crowns the result — the kind of "
        "phrase fans remember.\n"
        "- Keep it family-friendly and brand-safe: NO profanity, swear words or vulgar "
        "expressions (e.g. never 'de cojones', 'puto', 'hostia'). The passion comes from "
        "energy, imagery and rhythm — not from coarse language.\n"
        "STRICT: use ONLY the provided facts — never invent scorers, minutes, scores or plays. "
        f"{length} Output ONLY the spoken script: no headings, markdown, hashtags or stage directions."
    )

    user = (
        "Write the spoken highlight narration for this finished match:\n\n"
        f"{_facts_block(match)}"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return call_llm(messages, provider=provider, max_tokens=600, label="Narrator")


def _hashtag(text: str) -> str:
    """Turn a name into a CamelCase hashtag: 'Real Madrid' -> '#RealMadrid'."""
    parts = "".join(w.capitalize() for w in text.replace("-", " ").split())
    return f"#{parts}" if parts else ""


def build_tags(match: Match) -> list[str]:
    """Deterministic hashtags: competition + teams + countries + scorers +
    stadium + city — exactly the set the user asked for."""
    tags: list[str] = []
    # Competition (La Liga / World Cup ...).
    if match.competition:
        tags.append(_hashtag(match.competition))
    # Teams.
    tags += [_hashtag(match.home), _hashtag(match.away)]
    # Country (and an explicit World Cup tag when it's the World Cup).
    if "World Cup" in match.competition or "Mundial" in match.competition:
        tags.append("#WorldCup2026")
    if match.country:
        tags.append(_hashtag(match.country))
    # Scorers.
    for g in match.goals:
        t = _hashtag(g.player)
        if t and t not in tags:
            tags.append(t)
    # Stadium + city.
    if match.venue:
        tags.append(_hashtag(match.venue))
    if match.city:
        tags.append(_hashtag(match.city))
    tags.append("#Futbol")
    # Dedupe preserving order, drop empties.
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def youtube_metadata(match: Match, *, language: str = "es", provider: str | None = None) -> dict:
    """Generate a YouTube title + description (LLM) and deterministic tags."""
    lang = _LANG_NAME.get(language, "Spanish")
    system = (
        f"You generate a YouTube title and description in {lang}. Respond as JSON with "
        '"title" (<=90 chars, include the scoreline) and "description" (2-4 sentences). '
        "Use only the given facts. JSON only."
    )
    user = f"Match:\n{_facts_block(match)}"
    raw = call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider, max_tokens=400, label="YT-Meta",
    )
    import json

    from json_repair import repair_json
    try:
        data = json.loads(repair_json(raw))
    except Exception:
        data = {}
    return {
        "title": (data.get("title") or match.scoreline)[:90],
        "description": data.get("description") or match.scoreline,
        "tags": build_tags(match),
    }
