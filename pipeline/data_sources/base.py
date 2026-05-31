"""Base interface every football data source implements."""

from abc import ABC, abstractmethod

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
        """Finished matches not seen before (for the auto-scheduler)."""
        out = []
        for m in self.fixtures_on(day):
            if m.is_finished and m.fixture_id not in processed:
                full = self.fixture(m.fixture_id)
                processed.add(m.fixture_id)
                out.append(full)
        return out
