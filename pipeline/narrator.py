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


def youtube_metadata(match: Match, *, language: str = "es", provider: str | None = None) -> dict:
    """Generate a YouTube title, description and tags for the match video."""
    lang = _LANG_NAME.get(language, "Spanish")
    system = (
        f"You generate YouTube metadata in {lang}. Respond as a JSON object with keys "
        '"title" (<=90 chars), "description" (2-4 sentences), "tags" (list of 8-12 short '
        "strings). Use only the given facts. No markdown, JSON only."
    )
    user = f"Match:\n{_facts_block(match)}"
    raw = call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider, max_tokens=500, label="YT-Meta",
    )
    import json

    from json_repair import repair_json
    try:
        data = json.loads(repair_json(raw))
    except Exception:
        data = {}
    # Defensive defaults so the pipeline never breaks on a bad LLM response.
    return {
        "title": (data.get("title") or match.scoreline)[:90],
        "description": data.get("description") or match.scoreline,
        "tags": data.get("tags") or [match.home, match.away, "World Cup 2026", "football"],
    }
