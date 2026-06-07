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
    if match.venue:
        lines.append(f"Venue: {match.venue}")
    # Build ONE chronological list of every event (goals AND cards together),
    # so the narration can run through the match minute by minute.
    def _min(s):
        try:
            return int(str(s).split("+")[0])
        except ValueError:
            return 999

    events = []
    for g in match.goals:
        kind = "penalty goal" if "Pen" in g.kind else (
            "own goal" if "Own" in g.kind else "goal")
        line = f"minute {g.minute}: {kind} for {g.team}, scored by {g.player}"
        if g.description:
            line += f" — {g.description}"
        events.append((_min(g.minute), line))
    for c in match.cards:
        events.append((_min(c.minute),
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
    "full": "90-150 words.",
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

    system = (system_preamble + "\n\n" if system_preamble else "") + (
        f"You are a LEGENDARY, white-hot football play-by-play commentator. Write ONLY in {lang}. "
        "Narrate like a live radio announcer whose heart is about to burst — MAXIMUM passion, "
        "drama and emotion in every line:\n"
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
