"""
fallback.py — two sources for the SAME single club, one preferred.

Not to be confused with multi.py, which merges DIFFERENT competitions into one
feed. This pairs two providers that report the same club's matches, so the feed
survives one of them going quiet without the club appearing twice.

WHY IT EXISTS. Rōnin FC has two public sources and neither is sufficient alone:

    roninfc.fans (fcf.py)      the federation acta republished — scorers,
                               minutes, cards, referee. Far richer. But on
                               4 Sep 2026 it carried nothing at all of the
                               2026/27 season, not even the calendar.
    roninfc.digital            the scoreline, crests and kickoff, nothing more.
                               But it had the full Tercera Catalana fixture list
                               while the other was still showing May.

So the acta is the PRIMARY and stays the one that gets narrated whenever it
exists; the second source is only there to guarantee a match is noticed at all.
A video naming the scorers is much better than one that only states the result —
and both are better than silence, which is what the channel had.

ONE MATCH PER DAY is the assumption this whole module rests on, and it is only
sound because both legs follow a SINGLE CLUB: a football club plays at most one
fixture in a calendar day, so a day is enough to tell "these are the same match"
without comparing team names the two providers spell differently ("Peña
Recreativa San Feliu Llobregat" against "Pª Rec San Feliu Llobregat"). Do not
reuse this for a whole-league feed.
"""

from pipeline.match_monitor import Match

from .base import FootballDataSource


class FallbackSource(FootballDataSource):
    """`primary` if it knows about the day, otherwise `backup`."""

    name = "fallback"

    def __init__(self, primary: FootballDataSource, backup: FootballDataSource):
        self.primary = primary
        self.backup = backup
        # Ids from the backup are namespaced with its provider name so `fixture()`
        # can route a lookup back to the source that issued it. The primary's ids
        # are left untouched, so nothing that already exists on disk changes
        # meaning: an FCF acta id stays exactly what it always was.
        self._tag = f"{backup.name}-"
        # Days already served by the backup. Once a match has been filmed from
        # the scoreline, the primary publishing its acta hours later must NOT
        # produce a SECOND video of the same game — the ids differ, so the
        # scheduler's processed-set could not catch it on its own. Held in memory
        # for the life of the poller, which is the whole window that matters:
        # the scheduler only ever looks at yesterday and today.
        self._served_by_backup: set[str] = set()

    # ------------------------------------------------------------------
    def _tagged(self, match: Match) -> Match:
        if match is not None and not str(match.fixture_id).startswith(self._tag):
            match.fixture_id = f"{self._tag}{match.fixture_id}"
        return match

    def _merge(self, primary: list[Match], backup: list[Match]) -> list[Match]:
        """Primary's matches, plus backup's only for days primary cannot cover.

        "Cannot cover" is deliberately generous to the primary: a day it lists at
        all is its own, even if the fixture has not finished yet, because its
        acta is worth waiting a few hours for. The one exception is a day the
        backup has ALREADY served — see `_served_by_backup`.
        """
        known = {m.date for m in primary if m.date}
        out = list(primary)
        for m in backup:
            if not m.date:
                continue
            if m.date in known and m.date not in self._served_by_backup:
                continue
            if m.is_finished:
                self._served_by_backup.add(m.date)
            out.append(self._tagged(m))
        # A day the backup has taken over must not ALSO come through the primary,
        # or the same match is filmed twice under two different ids.
        return [m for m in out
                if not (m.date in self._served_by_backup
                        and not str(m.fixture_id).startswith(self._tag))]

    def _safe(self, call, source) -> list[Match]:
        """One dead source must not take the pair down — that is the point."""
        try:
            return list(call(source) or [])
        except Exception as e:  # noqa: BLE001
            print(f"[fallback] '{source.name}' failed ({e}) — skipped")
            return []

    # ------------------------------------------------------------------
    def fixtures_on(self, day: str | None = None) -> list[Match]:
        return self._merge(self._safe(lambda s: s.fixtures_on(day), self.primary),
                           self._safe(lambda s: s.fixtures_on(day), self.backup))

    def latest_finished(self, limit: int = 10) -> list[Match]:
        merged = self._merge(
            self._safe(lambda s: s.latest_finished(limit), self.primary),
            self._safe(lambda s: s.latest_finished(limit), self.backup))
        merged = [m for m in merged if m.is_finished]
        merged.sort(key=lambda m: (m.date or "", str(m.fixture_id)), reverse=True)
        return merged[:limit]

    def fixture(self, fixture_id) -> Match:
        raw = str(fixture_id)
        if raw.startswith(self._tag):
            return self._tagged(self.backup.fixture(raw[len(self._tag):]))
        return self.primary.fixture(raw)
