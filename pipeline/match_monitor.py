"""
match_monitor.py — fetch FIFA World Cup 2026 fixtures from API-Football and
detect finished matches to trigger video generation.

API-Football (api-sports.io) free tier: 100 requests/day, no card.
World Cup: league=1, season=2026. Match end states: FT / AET / PEN.

Designed to stay within the free quota: one `/fixtures` call returns every
match of the day with its status; `/fixtures/events` is only called once per
match, when it transitions to a finished state.

A clean, dependency-free dataclass (`Match`) is returned so the rest of the
pipeline never has to touch the raw API JSON.
"""

import os
from dataclasses import dataclass, field
from datetime import date

import requests

_BASE = "https://v3.football.api-sports.io"
_FINISHED = {"FT", "AET", "PEN"}


@dataclass
class Goal:
    player: str
    team: str
    minute: str          # "23" or "90+4"
    kind: str            # "Normal Goal", "Penalty", "Own Goal"


@dataclass
class Match:
    fixture_id: int
    status: str
    home: str
    away: str
    home_goals: int | None
    away_goals: int | None
    home_logo: str = ""
    away_logo: str = ""
    venue: str = ""
    goals: list[Goal] = field(default_factory=list)

    @property
    def is_finished(self) -> bool:
        return self.status in _FINISHED

    @property
    def scoreline(self) -> str:
        return f"{self.home} {self.home_goals}-{self.away_goals} {self.away}"


class MatchMonitor:
    """Polls API-Football and yields newly-finished matches (idempotent)."""

    def __init__(self, league_id: int = 1, season: int = 2026, api_key: str | None = None):
        self.league_id = league_id
        self.season = season
        self.api_key = api_key or os.getenv("APIFOOTBALL_KEY", "")
        self._processed: set[int] = set()

    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError("No APIFOOTBALL_KEY found in environment / .env")
        return {"x-apisports-key": self.api_key}

    def _get(self, path: str, params: dict) -> list:
        resp = requests.get(f"{_BASE}{path}", headers=self._headers(),
                            params=params, timeout=30)
        if resp.status_code == 429:
            raise RuntimeError("API-Football daily quota exhausted (HTTP 429). "
                               "Resets at 00:00 UTC.")
        resp.raise_for_status()
        return resp.json().get("response", [])

    # ------------------------------------------------------------------
    def fixtures_on(self, day: str | None = None) -> list[Match]:
        """Return all World Cup matches on `day` (YYYY-MM-DD, default today)."""
        day = day or date.today().isoformat()
        raw = self._get("/fixtures", {
            "league": self.league_id, "season": self.season, "date": day,
        })
        return [self._parse_fixture(f) for f in raw]

    def fixture(self, fixture_id: int) -> Match:
        """Return a single fixture with its goals populated."""
        raw = self._get("/fixtures", {"id": fixture_id})
        if not raw:
            raise ValueError(f"Fixture {fixture_id} not found")
        match = self._parse_fixture(raw[0])
        match.goals = self.goals_of(fixture_id)
        return match

    def goals_of(self, fixture_id: int) -> list[Goal]:
        """Fetch the goal events (scorer + minute) of a fixture."""
        events = self._get("/fixtures/events", {"fixture": fixture_id})
        goals = []
        for ev in events:
            if ev.get("type") != "Goal":
                continue
            t = ev.get("time", {})
            minute = str(t.get("elapsed", "?"))
            if t.get("extra"):
                minute = f"{minute}+{t['extra']}"
            goals.append(Goal(
                player=(ev.get("player") or {}).get("name", "Unknown"),
                team=(ev.get("team") or {}).get("name", ""),
                minute=minute,
                kind=ev.get("detail", "Normal Goal"),
            ))
        return goals

    # ------------------------------------------------------------------
    def poll_finished(self, day: str | None = None) -> list[Match]:
        """Return matches that JUST finished and were not processed before.

        Each returned match has its goals populated. Call this on a timer
        (every 1-2 min); already-processed fixture ids are remembered so a
        match is only ever returned once (no duplicate videos).
        """
        new_finished = []
        for m in self.fixtures_on(day):
            if m.is_finished and m.fixture_id not in self._processed:
                m.goals = self.goals_of(m.fixture_id)
                self._processed.add(m.fixture_id)
                new_finished.append(m)
        return new_finished

    def mark_processed(self, fixture_id: int) -> None:
        self._processed.add(fixture_id)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_fixture(f: dict) -> Match:
        fx = f.get("fixture", {})
        teams = f.get("teams", {})
        goals = f.get("goals", {})
        home, away = teams.get("home", {}), teams.get("away", {})
        return Match(
            fixture_id=fx.get("id"),
            status=(fx.get("status") or {}).get("short", "NS"),
            home=home.get("name", "Home"),
            away=away.get("name", "Away"),
            home_goals=goals.get("home"),
            away_goals=goals.get("away"),
            home_logo=home.get("logo", ""),
            away_logo=away.get("logo", ""),
            venue=(fx.get("venue") or {}).get("name", "") or "",
        )
