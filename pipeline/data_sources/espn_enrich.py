"""
espn_enrich.py — enrich a match with goal scorers + minutes from ESPN's public
(unofficial) API. Free, no key, no card.

ESPN is the only verified free source that exposes scorers with minute for the
FIFA World Cup 2026 (league slug 'fifa.world'). It also returns a rich textual
description of each goal ("left footed shot from the left side of the box..."),
which makes the narration far more vivid.

Strategy: take a Match that already has the final score (from TheSportsDB or
API-Football) and, if it has no goals, look it up on ESPN by team names + date
and attach the scorers. Provider-agnostic, used as an optional enrichment step.

Note: this is an undocumented API with no SLA; cache results and keep it as an
enhancement (the pipeline still works if ESPN is unavailable).
"""

import unicodedata
from datetime import date

import requests

from pipeline.match_monitor import Card, Goal, Match

from .espn import (
    _card_reason,
    _card_victims,
    _goal_kind,
    _key_notes,
    _team_stats,
    _with_victim,
    merge_second_yellow,
)

# League slug per competition. Extend as needed.
_LEAGUE_SLUG = {
    1: "fifa.world",      # API-Football World Cup id
    140: "esp.1",          # La Liga
    39: "eng.1",           # Premier League
    2: "uefa.champions",   # Champions League
    "4429": "fifa.world",  # TheSportsDB World Cup id
}


def _slug_for(cfg) -> str:
    """Resolve the ESPN league slug from the profile's competition."""
    explicit = cfg.get_secret("ESPN_LEAGUE_SLUG")
    if explicit:
        return explicit
    return (_LEAGUE_SLUG.get(cfg.LEAGUE_ID)
            or _LEAGUE_SLUG.get(str(getattr(cfg, "_tsdb_league", "")))
            or "fifa.world")


def _norm(name: str) -> str:
    """Normalise a team name for fuzzy matching across providers."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    aliases = {
        "usa": "united states", "korea republic": "south korea",
        "ir iran": "iran", "czech republic": "czechia",
    }
    return aliases.get(name, name)


def _base(slug: str) -> str:
    return f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}"


def _detail_from_summary(slug: str, event_id: str) -> dict:
    """One ESPN summary fetch -> {goals, cards, stats, notes}. Goals and cards
    carry the vivid play description / card reason; stats and notes power a
    richer, still-factual narration."""
    r = requests.get(f"{_base(slug)}/summary", params={"event": event_id}, timeout=20)
    r.raise_for_status()
    data = r.json()
    goals, cards = [], []
    victims = _card_victims(data)
    for ke in data.get("keyEvents", []):
        ttype = (ke.get("type") or {}).get("text", "")
        team = (ke.get("team") or {}).get("displayName", "")
        minute = str((ke.get("clock") or {}).get("displayValue", "?")).rstrip("'")
        parts = ke.get("participants") or [{}]
        player = (parts[0].get("athlete") or {}).get("displayName", "Unknown")
        if ke.get("scoringPlay") or ttype == "Goal":
            text = (ke.get("text") or "").strip()
            goals.append(Goal(
                player=player, team=team, minute=minute,
                kind=_goal_kind(ke, ttype, text),
                description=text,   # vivid play description
            ))
        elif "Card" in ttype or "card" in ttype.lower():
            color = "Red" if "Red" in ttype else "Yellow"
            cards.append(Card(player=player, team=team, minute=minute, color=color,
                              reason=_with_victim(_card_reason(ke.get("text")),
                                                  player, victims)))
    return {"goals": goals, "cards": merge_second_yellow(cards),
            "stats": _team_stats(data), "notes": _key_notes(data)}


def enrich(cfg, match: Match) -> Match:
    """Attach ESPN scorers, cards-with-reason, team stats and key notes to
    `match`. Returns the same Match. Best-effort: any failure leaves the match
    untouched and the pipeline still works."""
    # 0-0 has no scorers, but it can still carry cards and stats worth narrating.
    has_score = (match.home_goals or 0) + (match.away_goals or 0) > 0
    # Already fully enriched (goals + stats) — nothing more to fetch.
    if match.goals and match.stats:
        return match

    slug = _slug_for(cfg)
    # Find the ESPN event by date + team names. Use the match's date if known;
    # fall back to scanning a small window around today.
    try:
        for day in _candidate_dates(match):
            r = requests.get(f"{_base(slug)}/scoreboard",
                            params={"dates": day, "limit": 950}, timeout=20)
            if not r.ok:
                continue
            for ev in r.json().get("events", []):
                comp = ev["competitions"][0]
                names = {_norm(c["team"]["displayName"]) for c in comp["competitors"]}
                if _norm(match.home) in names and _norm(match.away) in names:
                    detail = _detail_from_summary(slug, ev["id"])
                    # Only fill what's missing — never overwrite goals the
                    # primary source already provided.
                    if not match.goals and has_score:
                        match.goals = detail["goals"]
                    if not match.cards:
                        match.cards = detail["cards"]
                    match.stats = match.stats or detail["stats"]
                    match.notes = match.notes or detail["notes"]
                    return match
    except Exception:
        pass  # enrichment is best-effort; never break the pipeline
    return match


def _candidate_dates(match: Match) -> list[str]:
    """Dates to probe on ESPN (YYYYMMDD). Uses today plus a small window."""
    today = date.today()
    from datetime import timedelta
    days = [today + timedelta(days=d) for d in (0, -1, -2, -3)]
    return [d.strftime("%Y%m%d") for d in days]
