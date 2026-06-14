"""
wc_calendar.py — FIFA World Cup 2026 schedule from openfootball (free, no key).

Downloads the public-domain openfootball worldcup.json (one fetch, all 104
matches) and groups it by day so the UI can show a calendar: matches per day,
teams, venue, the phase, and how many days remain. Cached on disk.

Source verified during research: a FLAT "matches" array, each item with
date (YYYY-MM-DD), time, team1, team2, group, round, ground.
"""

from datetime import date

import requests

_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

# Phase boundaries (from the verified per-day counts).
_PHASES = [
    ("Fase de grupos", "2026-06-11", "2026-06-27"),
    ("Dieciseisavos (R32)", "2026-06-28", "2026-07-03"),
    ("Octavos (R16)", "2026-07-04", "2026-07-07"),
    ("Cuartos", "2026-07-09", "2026-07-11"),
    ("Semifinales", "2026-07-14", "2026-07-15"),
    ("Tercer puesto", "2026-07-18", "2026-07-18"),
    ("Final", "2026-07-19", "2026-07-19"),
]


def _phase_for(day: str) -> str:
    for name, start, end in _PHASES:
        if start <= day <= end:
            return name
    return ""


def _team_name(t) -> str:
    """openfootball team field may be a string or a {name,...} object."""
    if isinstance(t, dict):
        return t.get("name") or t.get("code") or ""
    return str(t or "")


def fetch_calendar() -> list[dict]:
    """Return the schedule grouped by day, sorted ascending."""
    from .data_sources import cache
    key = ("wc_calendar", "2026")
    cached = cache.get(key)
    if cached is None:
        r = requests.get(_URL, timeout=30)
        r.raise_for_status()
        cached = r.json()
        cache.put(key, cached)

    matches = cached.get("matches", []) if isinstance(cached, dict) else []
    by_day: dict[str, list[dict]] = {}
    for m in matches:
        d = (m.get("date") or "")[:10]
        if not d:
            continue
        by_day.setdefault(d, []).append({
            "team1": _team_name(m.get("team1")),
            "team2": _team_name(m.get("team2")),
            "time": m.get("time", ""),
            "group": m.get("group", ""),
            "round": m.get("round", ""),
            "ground": (m.get("ground") or {}).get("name", "")
            if isinstance(m.get("ground"), dict) else (m.get("ground") or ""),
        })

    days = []
    for d in sorted(by_day):
        days.append({
            "date": d,
            "phase": _phase_for(d),
            "count": len(by_day[d]),
            "matches": by_day[d],
        })
    return days


def calendar_summary() -> dict:
    """High-level info: total matches, dates, next match-day and its size."""
    days = fetch_calendar()
    total = sum(d["count"] for d in days)
    today = date.today().isoformat()
    upcoming = [d for d in days if d["date"] >= today]
    next_day = upcoming[0] if upcoming else None
    return {
        "total_matches": total,
        "total_days": len(days),
        "start": days[0]["date"] if days else "",
        "end": days[-1]["date"] if days else "",
        "next_match_day": next_day["date"] if next_day else None,
        "next_match_day_count": next_day["count"] if next_day else 0,
        "days_until_next": (_days_between(today, next_day["date"]) if next_day else None),
        "days": days,
    }


def _days_between(a: str, b: str) -> int:
    from datetime import date as _d
    ya, ma, da = (int(x) for x in a.split("-"))
    yb, mb, db = (int(x) for x in b.split("-"))
    return (_d(yb, mb, db) - _d(ya, ma, da)).days
