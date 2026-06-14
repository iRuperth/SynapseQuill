"""Base interface every football data source implements."""

from abc import ABC, abstractmethod
from datetime import date, timedelta

from pipeline.match_monitor import Match


class FootballDataSource(ABC):
    """Common contract so the pipeline is provider-agnostic."""

    name: str = "base"

    @abstractmethod
    def fixtures_on(self, day: str | None = None) -> list[Match]:
        """All matches on a given date (YYYY-MM-DD, default today)."""

    @abstractmethod
    def latest_finished(self, limit: int = 10) -> list[Match]:
        """Most recent finished matches of the configured competition."""

    @abstractmethod
    def fixture(self, fixture_id) -> Match:
        """A single match with its goals populated (when available)."""

    def poll_finished(self, processed: set, day: str | None = None) -> list[Match]:
        """Finished matches not seen before (for the auto-scheduler).

        With no explicit day, BOTH yesterday and today are polled. Providers
        bucket fixtures by their OWN calendar — ESPN uses US Eastern — so a
        match kicking off late UTC, like every North American evening game of
        the 2026 World Cup, files under the PREVIOUS bucket once local
        midnight has passed. A today-only poll from Europe asks for the wrong
        bucket and never sees that match finish."""
        if day is not None:
            days = [day]
        else:
            today = date.today()
            days = [(today - timedelta(days=1)).isoformat(), today.isoformat()]
        out = []
        for d in days:
            for m in self.fixtures_on(d):
                if m.is_finished and m.fixture_id not in processed:
                    full = self.fixture(m.fixture_id)
                    processed.add(m.fixture_id)
                    out.append(full)
        return out
