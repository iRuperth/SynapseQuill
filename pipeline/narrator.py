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
            extra = "" if g.kind == "Normal Goal" else f" [{g.kind}]"
            lines.append(f"  - {g.minute}' {g.player} ({g.team}){extra}")
    else:
        lines.append("Goals: none scored (0-0).")
    if match.cards:
        lines.append("Cards:")
        for c in match.cards:
            lines.append(f"  - {c.minute}' {c.color} card, {c.player} ({c.team})")
    return "\n".join(lines)


def narrate(match: Match, *, language: str = "es", system_preamble: str = "",
            provider: str | None = None) -> str:
    """Return an exciting narration script for `match` in the given language."""
    lang = _LANG_NAME.get(language, "Spanish")

    system = (system_preamble + "\n\n" if system_preamble else "") + (
        f"You are an energetic football broadcaster. Write the narration ONLY in {lang}. "
        "Use the provided match facts and NOTHING else — never invent scorers, minutes "
        "or scores. Make it vivid and emotional, 90-140 words, ready to be read aloud. "
        "Do not add headings, markdown, hashtags or stage directions — just the spoken script."
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
