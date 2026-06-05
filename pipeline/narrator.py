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
    if match.goals:
        lines.append("Goals (in order):")
        for g in match.goals:
            extra = "" if g.kind == "Normal Goal" else f" ({g.kind})"
            lines.append(f"  - minute {g.minute}: goal for {g.team}, scored by "
                         f"{g.player}{extra}")
            if g.description:
                lines.append(f"      how it happened: {g.description}")
    else:
        lines.append("Goals: none scored (0-0).")
    if match.cards:
        lines.append("Cards:")
        for c in match.cards:
            lines.append(f"  - minute {c.minute}: {c.color} card for {c.player} "
                         f"of {c.team}")
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
        f"You are a CLASSIC, passionate football play-by-play commentator. Write ONLY in {lang}. "
        "Narrate like a live radio/TV announcer at peak excitement:\n"
        "- Short, explosive sentences. Build tension toward each goal.\n"
        "- Use interjections and stretched cheers on goals "
        "(in Spanish: '¡GOOOOOL!', '¡QUÉ GOLAZO!', '¡INCREÍBLE!'; in English: 'GOOOAL!', 'WHAT A STRIKE!').\n"
        "- Put the most intense words in CAPITALS for emphasis.\n"
        "- When 'how it happened' is given for a goal, describe the play vividly using it.\n"
        "- Mention the stadium and the drama of cards if present.\n"
        "- NEVER read team names in parentheses. Say them naturally — e.g. "
        "'gol del Girona, obra de Germán Martínez' or 'Germán Martínez marca para el Girona', "
        "never 'Germán Martínez (Girona)'.\n"
        "- End with an epic closing line about the result.\n"
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
