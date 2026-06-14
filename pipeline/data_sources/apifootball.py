"""
API-Football data source — full scorers + minutes (free plan: seasons 2021-2023).

Wraps the existing MatchMonitor so the provider interface stays thin.
"""

from pipeline.match_monitor import Match, MatchMonitor

from .base import FootballDataSource


class ApiFootballSource(FootballDataSource):
    name = "apifootball"

    def __init__(self, cfg):
        self.cfg = cfg
        self.monitor = MatchMonitor(
            cfg.LEAGUE_ID, cfg.SEASON, api_key=cfg.get_secret("APIFOOTBALL_KEY")
        )

    def fixtures_on(self, day: str | None = None) -> list[Match]:
        return self.monitor.fixtures_on(day)

    def latest_finished(self, limit: int = 10) -> list[Match]:
        return self.monitor.latest_finished(limit=limit)

    def fixture(self, fixture_id) -> Match:
        return self.monitor.fixture(int(fixture_id))
