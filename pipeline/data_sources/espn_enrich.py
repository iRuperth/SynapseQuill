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

from pipeline.match_monitor import Goal, Match

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


def _scorers_from_summary(slug: str, event_id: str) -> list[Goal]:
    r = requests.get(f"{_base(slug)}/summary", params={"event": event_id}, timeout=20)
    r.raise_for_status()
    data = r.json()
    goals = []
    for ke in data.get("keyEvents", []):
        if not (ke.get("scoringPlay") or (ke.get("type") or {}).get("text") == "Goal"):
            continue
        parts = ke.get("participants") or [{}]
        scorer = (parts[0].get("athlete") or {}).get("displayName", "Unknown")
        kind = "Penalty" if ke.get("penaltyKick") else (
            "Own Goal" if ke.get("ownGoal") else "Normal Goal")
        goals.append(Goal(
            player=scorer,
            team=(ke.get("team") or {}).get("displayName", ""),
            minute=str((ke.get("clock") or {}).get("displayValue", "?")).rstrip("'"),
            kind=kind,
            description=(ke.get("text") or "").strip(),   # vivid play description
        ))
    return goals


def enrich(cfg, match: Match) -> Match:
    """Attach ESPN scorers to `match` if it has none. Returns the same Match."""
    if match.goals:
        return match
    if (match.home_goals or 0) + (match.away_goals or 0) == 0:
        return match  # 0-0, nothing to enrich

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
                    match.goals = _scorers_from_summary(slug, ev["id"])
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
