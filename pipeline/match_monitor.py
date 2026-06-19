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
    description: str = ""  # how it happened, e.g. "left footed shot..." (from ESPN)


@dataclass
class Card:
    player: str
    team: str
    minute: str
    color: str           # "Yellow" or "Red"
    reason: str = ""     # why it was shown, e.g. "a bad foul" (from ESPN); the
    #                      narrator may state this ONLY because it is a fact,
    #                      never invented. Empty when the provider gives no cause.


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
    city: str = ""
    country: str = ""
    competition: str = ""          # real league/cup name (not hardcoded)
    date: str = ""                 # YYYY-MM-DD
    kickoff: str = ""              # full ISO datetime in UTC, e.g. 2026-06-08T19:00Z
    goals: list[Goal] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    # Penalty shootout (knockout games that ended level). Populated when the
    # provider exposes it (ESPN does). None when there was no shootout.
    home_pens: int | None = None
    away_pens: int | None = None
    # Optional ESPN enrichment for a richer, still-factual narration. Both are
    # best-effort (empty when the provider gives nothing) and are passed to the
    # narrator as facts, never invented.
    #   stats: {team_name: {"possession": 53.0, "shots": 11, "shots_on": 5,
    #                       "corners": 6, "fouls": 12}} — from ESPN boxscore.
    #   notes: short factual play-by-play notes the keyEvents miss (VAR
    #          overturns, goals off the post/bar, missed penalties), each
    #          "minute · text", already in chronological order.
    stats: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_finished(self) -> bool:
        return self.status in _FINISHED

    @property
    def scoreline(self) -> str:
        return f"{self.home} {self.home_goals}-{self.away_goals} {self.away}"

    @property
    def went_to_penalties(self) -> bool:
        return self.home_pens is not None and self.away_pens is not None

    @property
    def winner(self) -> str | None:
        """The winning team's name, or None on a draw / unknown score. When the
        game was level and decided on penalties, the shootout winner wins."""
        if self.home_goals is None or self.away_goals is None:
            return None
        if self.home_goals > self.away_goals:
            return self.home
        if self.away_goals > self.home_goals:
            return self.away
        # Level after normal/extra time — fall back to the shootout result.
        if self.went_to_penalties and self.home_pens != self.away_pens:
            return self.home if self.home_pens > self.away_pens else self.away
        return None

    @property
    def is_draw(self) -> bool:
        return (self.home_goals is not None and self.away_goals is not None
                and self.home_goals == self.away_goals)


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
    def _parse_list(self, raw: list) -> list[Match]:
        """Parse fixtures, dropping any without a usable id."""
        out = []
        for f in raw:
            m = self._parse_fixture(f)
            if m.fixture_id is not None:
                out.append(m)
        return out

    def fixtures_on(self, day: str | None = None) -> list[Match]:
        """Return all matches on `day` (YYYY-MM-DD, default today)."""
        day = day or date.today().isoformat()
        raw = self._get("/fixtures", {
            "league": self.league_id, "season": self.season, "date": day,
        })
        return self._parse_list(raw)

    def fixtures_between(self, frm: str, to: str) -> list[Match]:
        """Return all matches in a date range (YYYY-MM-DD). Useful for historical
        seasons where 'today' has no games (e.g. demoing a past La Liga round)."""
        raw = self._get("/fixtures", {
            "league": self.league_id, "season": self.season, "from": frm, "to": to,
        })
        return self._parse_list(raw)

    def fixtures_round(self, round_name: str) -> list[Match]:
        """Return all matches of a given round, e.g. 'Regular Season - 38'."""
        raw = self._get("/fixtures", {
            "league": self.league_id, "season": self.season, "round": round_name,
        })
        return self._parse_list(raw)

    def latest_finished(self, limit: int = 10) -> list[Match]:
        """Return the most recent finished matches of the configured competition.

        Fetches the whole season's fixtures in one call (so it works for any
        historical season — La Liga 2023, World Cup 2022 — regardless of how long
        ago it ended) and returns the last finished ones, most recent first.
        """
        raw = self._get("/fixtures", {"league": self.league_id, "season": self.season})
        finished = [m for m in self._parse_list(raw) if m.is_finished]
        # Sort by kickoff date (most recent first); fixture_id as tiebreaker.
        finished.sort(key=lambda m: (m.date or "", m.fixture_id or 0), reverse=True)
        return finished[:limit]

    def fixture(self, fixture_id: int) -> Match:
        """Return a single fixture with its goals and cards populated."""
        raw = self._get("/fixtures", {"id": fixture_id})
        if not raw:
            raise ValueError(f"Fixture {fixture_id} not found")
        match = self._parse_fixture(raw[0])
        match.goals, match.cards = self.events_of(fixture_id)
        return match

    @staticmethod
    def _minute(ev: dict) -> str:
        t = ev.get("time", {})
        minute = str(t.get("elapsed", "?"))
        if t.get("extra"):
            minute = f"{minute}+{t['extra']}"
        return minute

    def events_of(self, fixture_id: int) -> tuple[list[Goal], list[Card]]:
        """Fetch goals (scorer + minute) and cards (player + colour + minute)."""
        events = self._get("/fixtures/events", {"fixture": fixture_id})
        goals, cards = [], []
        for ev in events:
            etype = ev.get("type")
            player = (ev.get("player") or {}).get("name", "Unknown")
            team = (ev.get("team") or {}).get("name", "")
            if etype == "Goal":
                goals.append(Goal(player=player, team=team, minute=self._minute(ev),
                                  kind=ev.get("detail", "Normal Goal")))
            elif etype == "Card":
                detail = ev.get("detail", "")
                color = "Red" if "Red" in detail else "Yellow"
                cards.append(Card(player=player, team=team,
                                  minute=self._minute(ev), color=color))
        return goals, cards

    def goals_of(self, fixture_id: int) -> list[Goal]:
        """Backwards-compatible helper returning only the goals."""
        return self.events_of(fixture_id)[0]

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
        league = f.get("league", {})
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
            city=(fx.get("venue") or {}).get("city", "") or "",
            country=league.get("country", "") or "",
            competition=league.get("name", "") or "",
            date=(fx.get("date", "") or "")[:10],
        )
