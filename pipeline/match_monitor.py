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
# Finished-match statuses across providers: API-Football (FT/AET/PEN) and
# TheSportsDB (Match Finished / Finished).
_FINISHED = {"FT", "AET", "PEN", "Match Finished", "Finished"}


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
        from .data_sources import cache
        cache_key = ("apifootball", path, tuple(sorted(params.items())))

        # Serve fresh cache first to avoid spending the 100/day quota.
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            resp = requests.get(f"{_BASE}{path}", headers=self._headers(),
                                params=params, timeout=30)
        except requests.RequestException:
            stale = cache.get_stale(cache_key)
            if stale is not None:
                return stale
            raise

        if resp.status_code == 429:
            # Quota exhausted: fall back to stale cache if we have any.
            stale = cache.get_stale(cache_key)
            if stale is not None:
                return stale
            raise RuntimeError("API-Football daily quota exhausted (HTTP 429). "
                               "Resets at 00:00 UTC.")
        resp.raise_for_status()
        data = resp.json().get("response", [])
        cache.put(cache_key, data)
        return data

    # ------------------------------------------------------------------
    def fixtures_on(self, day: str | None = None) -> list[Match]:
        """Return all matches on `day` (YYYY-MM-DD, default today)."""
        day = day or date.today().isoformat()
        raw = self._get("/fixtures", {
            "league": self.league_id, "season": self.season, "date": day,
        })
        return [self._parse_fixture(f) for f in raw]

    def fixtures_between(self, frm: str, to: str) -> list[Match]:
        """Return all matches in a date range (YYYY-MM-DD). Useful for historical
        seasons where 'today' has no games (e.g. demoing a past La Liga round)."""
        raw = self._get("/fixtures", {
            "league": self.league_id, "season": self.season, "from": frm, "to": to,
        })
        return [self._parse_fixture(f) for f in raw]

    def fixtures_round(self, round_name: str) -> list[Match]:
        """Return all matches of a given round, e.g. 'Regular Season - 38'."""
        raw = self._get("/fixtures", {
            "league": self.league_id, "season": self.season, "round": round_name,
        })
        return [self._parse_fixture(f) for f in raw]

    def latest_finished(self, limit: int = 10) -> list[Match]:
        """Return the most recent finished matches of the configured competition.

        Fetches the whole season's fixtures in one call (so it works for any
        historical season — La Liga 2023, World Cup 2022 — regardless of how long
        ago it ended) and returns the last finished ones, most recent first.
        """
        raw = self._get("/fixtures", {"league": self.league_id, "season": self.season})
        matches = [self._parse_fixture(f) for f in raw]
        finished = [m for m in matches if m.is_finished]
        finished.sort(key=lambda m: m.fixture_id, reverse=True)
        return finished[:limit]

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
