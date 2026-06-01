"""
TheSportsDB data source — covers the FIFA World Cup 2026 (idLeague=4429).

Free test key '123', no card. Final scores are available for free; per-goal
scorer+minute timeline is a paid v2 feature, so goals come back empty on the
free tier (the narration then summarises the result without naming scorers).

Config (env / profile):
    THESPORTSDB_KEY      free test key (default '123')
    THESPORTSDB_LEAGUE   league id (default 4429 = FIFA World Cup)
    THESPORTSDB_SEASON   e.g. '2026'
"""

import os

import requests

from pipeline.match_monitor import Goal, Match

from .base import FootballDataSource

_FINISHED = {"Match Finished", "FT", "AET", "PEN", "Finished"}


class TheSportsDbSource(FootballDataSource):
    name = "thesportsdb"

    def __init__(self, cfg):
        self.cfg = cfg
        self.key = cfg.get_secret("THESPORTSDB_KEY") or os.getenv("THESPORTSDB_KEY", "123")
        # Prefer the league id resolved by the competition preset on the profile.
        self.league = (getattr(cfg, "_tsdb_league", None)
                       or cfg.get_secret("THESPORTSDB_LEAGUE")
                       or os.getenv("THESPORTSDB_LEAGUE", "4429"))
        self.season = cfg.get_secret("THESPORTSDB_SEASON") or os.getenv("THESPORTSDB_SEASON", "2026")
        self.base = f"https://www.thesportsdb.com/api/v1/json/{self.key}"

    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict) -> dict:
        r = requests.get(f"{self.base}/{path}", params=params, timeout=30)
        if r.status_code == 429:
            raise RuntimeError("TheSportsDB rate limit (HTTP 429). Wait a minute.")
        r.raise_for_status()
        return r.json() or {}

    def _to_match(self, e: dict) -> Match:
        def _int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        return Match(
            fixture_id=e.get("idEvent"),
            status=e.get("strStatus") or ("FT" if e.get("intHomeScore") is not None else "NS"),
            home=e.get("strHomeTeam", "Home"),
            away=e.get("strAwayTeam", "Away"),
            home_goals=_int(e.get("intHomeScore")),
            away_goals=_int(e.get("intAwayScore")),
            home_logo=e.get("strHomeTeamBadge", "") or "",
            away_logo=e.get("strAwayTeamBadge", "") or "",
            venue=e.get("strVenue", "") or "",
        )

    # ------------------------------------------------------------------
    def fixtures_on(self, day: str | None = None) -> list[Match]:
        from datetime import date
        day = day or date.today().isoformat()
        data = self._get("eventsday.php", {"d": day, "s": "Soccer"})
        events = data.get("events") or []
        # Keep only this competition.
        events = [e for e in events if str(e.get("idLeague")) == str(self.league)]
        return [self._to_match(e) for e in events]

    def latest_finished(self, limit: int = 10) -> list[Match]:
        # eventspastleague returns the last played matches of a league.
        data = self._get("eventspastleague.php", {"id": self.league})
        events = data.get("events") or []
        matches = [self._to_match(e) for e in events]
        finished = [m for m in matches if m.is_finished or m.home_goals is not None]
        return finished[:limit]

    def fixture(self, fixture_id) -> Match:
        data = self._get("lookupevent.php", {"id": fixture_id})
        events = data.get("events") or []
        if not events:
            raise ValueError(f"Event {fixture_id} not found on TheSportsDB")
        match = self._to_match(events[0])
        match.goals = self._goals(fixture_id)
        return match

    # ------------------------------------------------------------------
    def _goals(self, event_id) -> list[Goal]:
        """Goal timeline — present only on paid v2; returns [] on the free tier."""
        try:
            data = self._get("lookuptimeline.php", {"id": event_id})
        except Exception:
            return []
        goals = []
        for x in data.get("timeline") or []:
            if x.get("strTimeline") == "Goal":
                goals.append(Goal(
                    player=x.get("strPlayer", "Unknown"),
                    team=x.get("strTeam", ""),
                    minute=str(x.get("intTime", "?")),
                    kind="Normal Goal",
                ))
        return goals

    def is_finished(self, status: str) -> bool:
        return status in _FINISHED
