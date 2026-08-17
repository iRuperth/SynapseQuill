"""
multi.py — one feed built from SEVERAL data sources, each optionally narrowed
to a single team.

The channel covers two things that share no provider: every LaLiga match (ESPN)
and every match of one specific club wherever it plays (its own source). Rather
than teach the pipeline about two feeds, this presents them as ONE
FootballDataSource, so runner/digest/scheduler stay unchanged.

Each leg is a `Leg`:
    source  any FootballDataSource
    team    "" to take every match the source returns, or a club name to keep
            only the matches that club plays — HOME OR AWAY

The team filter is what makes a whole-league source usable as a follow-one-club
feed, and it is matched loosely (accent- and case-insensitive, on either side)
because the same club is spelled differently by different providers.

Every match is re-keyed as "<leg>-<id>" ("laliga-401882920"). Two reasons:
`fixture()` has to know WHICH leg owns an id to route the lookup, and ids from
unrelated provider databases can collide — the record files, the scheduler's
processed-set and the digest all key off `fixture_id`, so a collision would
silently drop a match as "already generated". The separator is "-" and not ":"
because these ids become filenames, and ":" is displayed as "/" by the macOS
Finder.
"""

import unicodedata

from pipeline.match_monitor import Match

from .base import FootballDataSource


def _fold(s: str) -> str:
    """Lower-case, accent-stripped form for tolerant team-name matching."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if not unicodedata.combining(c)).strip()


class Leg:
    """One source in the feed, optionally narrowed to a single club."""

    def __init__(self, key: str, source: FootballDataSource, team: str = ""):
        self.key = key
        self.source = source
        self.team = team

    def wants(self, match: Match) -> bool:
        """True when this match belongs in the feed. No team -> everything."""
        if not self.team:
            return True
        want = _fold(self.team)
        # Substring either way: the provider may print "Rōnin F.C." where the
        # config says "Rōnin FC", or the short "Ronin" against a long official
        # name. Both sides are folded, so accents never decide a match.
        return any(want in _fold(side) or _fold(side) in want
                   for side in (match.home, match.away) if side)

    def tag(self, match: Match) -> Match:
        """Namespace the fixture id so ids from different providers can't clash."""
        if match is not None and not str(match.fixture_id).startswith(f"{self.key}-"):
            match.fixture_id = f"{self.key}-{match.fixture_id}"
        return match


class MultiSource(FootballDataSource):
    """Several sources presented as one feed."""

    name = "multi"

    def __init__(self, legs: list[Leg]):
        self.legs = legs

    # ------------------------------------------------------------------
    def _leg_for(self, fixture_id) -> tuple[Leg, str]:
        """Split a namespaced id back into (leg, provider's own id).

        Matched against the known leg keys rather than by splitting on the first
        "-", because a provider's own id may itself contain one.
        """
        raw = str(fixture_id)
        for leg in self.legs:
            if raw.startswith(f"{leg.key}-"):
                return leg, raw[len(leg.key) + 1:]
        # Un-namespaced id (a hand-typed --match, or an older record): fall back
        # to the first leg, which is the channel's primary competition.
        return self.legs[0], raw

    def _gather(self, call) -> list[Match]:
        """Run `call` on every leg, keeping only the matches that leg wants.

        A failing leg must not take the whole feed down: if the club's small
        federation site is unreachable, LaLiga still has to publish.
        """
        out: list[Match] = []
        for leg in self.legs:
            try:
                for m in call(leg) or []:
                    if leg.wants(m):
                        out.append(leg.tag(m))
            except Exception as e:  # noqa: BLE001
                print(f"[multi] leg '{leg.key}' failed ({e}) — skipped")
        return out

    # ------------------------------------------------------------------
    def fixtures_on(self, day: str | None = None) -> list[Match]:
        matches = self._gather(lambda leg: leg.source.fixtures_on(day))
        matches.sort(key=lambda m: (m.date or "", m.kickoff or ""))
        return matches

    def latest_finished(self, limit: int = 10) -> list[Match]:
        # Ask each leg for the full limit, then keep the most recent overall —
        # taking limit/len(legs) from each would hide a busy LaLiga weekend
        # behind a single amateur fixture.
        matches = self._gather(lambda leg: leg.source.latest_finished(limit))
        matches = [m for m in matches if m.is_finished]
        matches.sort(key=lambda m: (m.date or "", m.kickoff or ""), reverse=True)
        return matches[:limit]

    def fixture(self, fixture_id) -> Match:
        leg, raw = self._leg_for(fixture_id)
        return leg.tag(leg.source.fixture(raw))
