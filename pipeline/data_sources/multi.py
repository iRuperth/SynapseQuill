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

import re
import unicodedata

from pipeline.match_monitor import Match

from .base import FootballDataSource


def _fold(s: str) -> str:
    """Lower-case, accent-stripped form for tolerant team-name matching."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if not unicodedata.combining(c)).strip()


def _as_list(value: list[str] | str) -> list[str]:
    """Normalise a config value that may be one club or a list of them."""
    if isinstance(value, str):
        value = [value] if value else []
    return [v for v in value if v]


# Knockout stages that carry a whole competition on their own. A Copa del Rey
# final between two modest clubs is still the biggest football story of the week,
# so these pass the club filter regardless of who is playing. The strings are
# ESPN's own stage vocabulary, which Match.round is populated with.
DEFAULT_ALWAYS_ROUNDS = ("quarterfinals", "semifinals", "final")


def _words(name: str) -> set:
    """Fold a club name to its set of words, punctuation dropped.

    "Rōnin F.C." and "RONIN FC" both become {"ronin", "f", "c"}, so the same
    club spelled differently by two providers still compares equal.
    """
    return {w for w in re.split(r"[^a-z0-9]+", _fold(name)) if w}


def _plays(match: Match, teams: list[str]) -> bool:
    """True when one of `teams` is playing, home or away.

    Matched on WHOLE WORDS, subset either way: the config's "Atletico Madrid"
    has to match the provider's "Club Atletico de Madrid", and the config's
    "Rōnin" has to match "Rōnin F.C.", so neither side can be required to be
    complete. But a plain substring test is wrong in a way that publishes actual
    mistakes — "ronin" is a substring of "Gironina", so a Gironina fixture the
    club never played would be picked up as one of theirs and narrated as such.
    Comparing sets of words keeps both real cases and rejects that one.
    """
    if match is None:
        return False
    sides = [_words(side) for side in (match.home, match.away) if side]
    wanted = [_words(t) for t in teams]
    return any(want <= side or side <= want
               for want in wanted if want for side in sides if side)


class Leg:
    """One source in the feed, with two INDEPENDENT filters.

    They answer different questions and must not be conflated:

    `teams` — does this match belong in the feed AT ALL? It is what turns a
        whole-league source into a follow-one-club feed. Empty means "everything
        this source returns", which is how LaLiga and the cup competitions are
        configured: the whole competition is covered, because the round-up is
        supposed to account for all of it.

    `video_teams` — of the matches that DID make it in, which deserve a video of
        their own? Empty means all of them. This is the lever that keeps the
        Champions League and the Copa del Rey in the channel without filming 25
        first-round ties between clubs nobody has heard of: they land in their
        round's recap and nowhere else.

    Filtering feed membership by club instead would drop those matches entirely,
    and the recap that claims to cover the round would quietly omit most of it.

    `always_rounds` overrides `video_teams` — a quarter-final onwards is filmed
    whoever reached it. `per_match` switches individual videos off wholesale.
    """

    def __init__(self, key: str, source: FootballDataSource,
                 teams: list[str] | str = "", *,
                 video_teams: list[str] | str = "",
                 per_match: bool = True,
                 always_rounds: list[str] | tuple[str, ...] | None = None):
        self.key = key
        self.source = source
        # A bare string is accepted so a one-club leg reads naturally in the
        # config (`"team": "Rōnin"`) and so older single-club specs keep working.
        self.teams = _as_list(teams)
        self.video_teams = _as_list(video_teams)
        self.per_match = per_match
        self.always_rounds = tuple(DEFAULT_ALWAYS_ROUNDS if always_rounds is None
                                   else always_rounds)

    def wants(self, match: Match) -> bool:
        """True when this match belongs in the feed. No clubs -> everything."""
        return True if not self.teams else _plays(match, self.teams)

    def wants_own_video(self, match: Match) -> bool:
        """True when this match earns a video of its own rather than a mention."""
        if not self.per_match or match is None or not self.wants(match):
            return False
        if not self.video_teams:
            return True
        # A late knockout round stands on its own merits, whoever reached it:
        # a Copa del Rey final between two modest clubs is still the story of
        # the week.
        if (match.round or "") in self.always_rounds:
            return True
        return _plays(match, self.video_teams)

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

    def wants_own_video(self, match: Match) -> bool:
        """True when this match gets its own video, False for digest-only.

        A leg can be worth covering without being worth filming match by match:
        the early rounds of the Copa del Rey put 25 fixtures on one Wednesday,
        nearly all of them between clubs the audience has never heard of. Those
        belong in the round's recap, not in 25 separate uploads. The leg's own
        `wants()` has already decided the match belongs in the feed at all.
        """
        if match is None:
            return False
        leg, _raw = self._leg_for(match.fixture_id)
        return leg.wants_own_video(match)

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
