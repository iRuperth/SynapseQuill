"""
espn.py — ESPN public (unofficial) API as a PRIMARY football data source.

Verified live (June 2026) to provide CURRENT-season data — La Liga 2025/26 and
the FIFA World Cup 2026 — with final scores AND scorers+minutes, for FREE with
no API key. This is what lets the app show recent matches (not old seasons).

League slug per competition (ESPN naming):
    esp.1         La Liga (Spanish Primera División)
    fifa.world    FIFA World Cup

Returns the shared Match/Goal/Card dataclasses so the pipeline stays
provider-agnostic. Undocumented API: cache responses and keep it best-effort.
"""

import os
from datetime import date, timedelta

import requests

from pipeline.match_monitor import Card, Goal, Match

from .base import FootballDataSource

_FINISHED_STATES = {"STATUS_FULL_TIME", "STATUS_FINAL"}


class EspnSource(FootballDataSource):
    name = "espn"

    def __init__(self, cfg):
        self.cfg = cfg
        self.slug = (cfg.get_secret("ESPN_LEAGUE_SLUG")
                     or getattr(cfg, "ESPN_SLUG", None)
                     or os.getenv("ESPN_LEAGUE_SLUG", "esp.1"))
        self.base = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{self.slug}"

    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict) -> dict:
        from . import cache
        key = ("espn", self.slug, path, tuple(sorted(params.items())))
        cached = cache.get(key)
        if cached is not None:
            return cached
        r = requests.get(f"{self.base}/{path}", params=params, timeout=30)
        if not r.ok:
            stale = cache.get_stale(key)
            if stale is not None:
                return stale
            r.raise_for_status()
        data = r.json()
        cache.put(key, data)
        return data

    # ------------------------------------------------------------------
    def _event_to_match(self, ev: dict) -> Match:
        comp = (ev.get("competitions") or [{}])[0]
        competitors = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        home, away = competitors.get("home", {}), competitors.get("away", {})

        def _name(c):
            return (c.get("team") or {}).get("displayName", "")

        def _score(c):
            try:
                return int(c.get("score"))
            except (TypeError, ValueError):
                return None

        venue = (comp.get("venue") or {})
        status = ((ev.get("status") or {}).get("type") or {}).get("name", "")
        return Match(
            fixture_id=int(ev["id"]) if str(ev.get("id", "")).isdigit() else ev.get("id"),
            status="FT" if status in _FINISHED_STATES else status or "NS",
            home=_name(home), away=_name(away),
            home_goals=_score(home), away_goals=_score(away),
            home_logo=(home.get("team") or {}).get("logo", "") or "",
            away_logo=(away.get("team") or {}).get("logo", "") or "",
            venue=venue.get("fullName", "") or "",
            city=(venue.get("address") or {}).get("city", "") or "",
            country=(venue.get("address") or {}).get("country", "") or "",
            competition=(ev.get("league") or {}).get("name", "")
            or self._league_name(ev),
            date=(ev.get("date", "") or "")[:10],
        )

    @staticmethod
    def _league_name(ev: dict) -> str:
        # scoreboard puts the league name at the top level, not on the event.
        return ""

    # ------------------------------------------------------------------
    def _scoreboard(self, dates: str) -> list[Match]:
        data = self._get("scoreboard", {"dates": dates, "limit": 300})
        league_name = ((data.get("leagues") or [{}])[0]).get("name", "")
        matches = []
        for ev in data.get("events", []):
            m = self._event_to_match(ev)
            if not m.competition:
                m.competition = league_name
            matches.append(m)
        return matches

    def fixtures_on(self, day: str | None = None) -> list[Match]:
        day = (day or date.today().isoformat()).replace("-", "")
        return self._scoreboard(day)

    def latest_finished(self, limit: int = 10) -> list[Match]:
        # Scan the last ~45 days; return the most recent finished matches.
        end = date.today()
        start = end - timedelta(days=45)
        rng = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
        matches = self._scoreboard(rng)
        finished = [m for m in matches if m.is_finished]
        finished.sort(key=lambda m: (m.date or "", m.fixture_id or 0), reverse=True)
        return finished[:limit]

    def fixture(self, fixture_id) -> Match:
        data = self._get("summary", {"event": str(fixture_id)})
        header = (data.get("header") or {})
        comp = (header.get("competitions") or [{}])[0]
        competitors = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        home, away = competitors.get("home", {}), competitors.get("away", {})

        def _name(c):
            return (c.get("team") or {}).get("displayName", "")

        def _score(c):
            try:
                return int(c.get("score"))
            except (TypeError, ValueError):
                return None

        gameinfo = (data.get("gameInfo") or {})
        venue = (gameinfo.get("venue") or {})
        league = (header.get("league") or {})
        status = ((comp.get("status") or {}).get("type") or {}).get("name", "")
        match = Match(
            fixture_id=int(fixture_id) if str(fixture_id).isdigit() else fixture_id,
            status="FT" if status in _FINISHED_STATES else status or "FT",
            home=_name(home), away=_name(away),
            home_goals=_score(home), away_goals=_score(away),
            home_logo=(home.get("team") or {}).get("logos", [{}])[0].get("href", "")
            if (home.get("team") or {}).get("logos") else (home.get("team") or {}).get("logo", ""),
            away_logo=(away.get("team") or {}).get("logos", [{}])[0].get("href", "")
            if (away.get("team") or {}).get("logos") else (away.get("team") or {}).get("logo", ""),
            venue=venue.get("fullName", "") or "",
            city=(venue.get("address") or {}).get("city", "") or "",
            country=(venue.get("address") or {}).get("country", "") or "",
            competition=league.get("name", "") or "",
            date=(header.get("date") or comp.get("date", "") or "")[:10],
        )
        match.goals, match.cards = self._events(data)
        return match

    # ------------------------------------------------------------------
    @staticmethod
    def _events(summary: dict) -> tuple[list[Goal], list[Card]]:
        goals, cards = [], []
        for ke in summary.get("keyEvents", []):
            ttype = (ke.get("type") or {}).get("text", "")
            minute = str((ke.get("clock") or {}).get("displayValue", "?")).rstrip("'")
            team = (ke.get("team") or {}).get("displayName", "")
            parts = ke.get("participants") or [{}]
            player = (parts[0].get("athlete") or {}).get("displayName", "Unknown")
            if ke.get("scoringPlay") or ttype == "Goal":
                kind = "Penalty" if ke.get("penaltyKick") else (
                    "Own Goal" if ke.get("ownGoal") else "Normal Goal")
                goals.append(Goal(player=player, team=team, minute=minute, kind=kind,
                                  description=(ke.get("text") or "").strip()))
            elif "Card" in ttype or "card" in ttype.lower():
                color = "Red" if "Red" in ttype else "Yellow"
                cards.append(Card(player=player, team=team, minute=minute, color=color))
        return goals, cards
