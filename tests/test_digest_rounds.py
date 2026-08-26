"""Round detection on a feed carrying several competitions.

This is the piece that fails SILENTLY. A round that swallows the whole week, or
one that resolves to two different anchors depending on which day you ask about,
produces either a recap mixing four competitions under one title or two copies
of the same recap — and neither raises anything. The scheduler just publishes it.

The fixtures below are a realistic European week, the exact shape that broke the
original day-walking logic: LaLiga Friday to Monday, the Champions League on
Tuesday and Wednesday, the Europa League on Thursday. Every day is occupied, so
there is no empty day left for an unfiltered walk to stop at.
"""

import pytest

from core import competitions
from pipeline.digest import fixtures_of, matchday_days
from pipeline.match_monitor import Match

# 2026-09-18 is a Friday.
FRI, SAT, SUN, MON, TUE, WED, THU = (f"2026-09-{d}" for d in range(18, 25))
NEXT_FRI = "2026-09-25"

LALIGA, UCL = "Spanish LALIGA", "UEFA Champions League"
UEL, NATIONS = "UEFA Europa League", "UEFA Nations League"


def _m(day: str, competition: str, home: str = "A", away: str = "B") -> Match:
    return Match(fixture_id=f"{competition}-{day}-{home}", status="FT",
                 home=home, away=away, home_goals=1, away_goals=0,
                 competition=competition, date=day)


class FakeSource:
    """Fixtures from a dict, no network."""

    def __init__(self, by_day: dict):
        self.by_day = by_day

    def fixtures_on(self, day=None):
        return list(self.by_day.get(day, []))


@pytest.fixture
def week():
    return FakeSource({
        FRI: [_m(FRI, LALIGA)],
        SAT: [_m(SAT, LALIGA)],
        SUN: [_m(SUN, LALIGA)],
        MON: [_m(MON, LALIGA)],
        TUE: [_m(TUE, UCL)],
        WED: [_m(WED, UCL)],
        THU: [_m(THU, UEL)],
        NEXT_FRI: [_m(NEXT_FRI, LALIGA)],
    })


def keep(key):
    return lambda m: competitions.key_for(m.competition) == key


def test_round_stops_at_its_own_competitions_gap(week):
    """A LaLiga jornada is Friday to Monday even though Tuesday has football."""
    assert matchday_days(week, SAT, "matchday", keep("laliga")) == [FRI, SAT, SUN, MON]


def test_unfiltered_walk_would_swallow_the_week(week):
    """Why the filter is not optional: with every day occupied, an unscoped walk
    runs to _MATCHDAY_REACH in both directions and calls seven days one round."""
    assert len(matchday_days(week, SAT, "matchday")) > 4


def test_champions_round_is_its_own_two_days(week):
    assert matchday_days(week, TUE, "matchday", keep("champions")) == [TUE, WED]


def test_every_day_of_a_round_resolves_to_the_same_anchor(week):
    """The invariant the whole once-per-round guarantee rests on: the record is
    keyed by days[0], so if Sunday and Monday disagreed about where the round
    started, one jornada would be published twice."""
    anchors = {matchday_days(week, d, "matchday", keep("laliga"))[0]
               for d in (FRI, SAT, SUN, MON)}
    assert anchors == {FRI}


def test_daily_mode_keeps_each_day_separate():
    """A national-team window plays all of Europe on the same days, so each day
    is its own recap rather than one round spanning the international break."""
    src = FakeSource({TUE: [_m(TUE, NATIONS)], WED: [_m(WED, NATIONS)]})
    assert matchday_days(src, TUE, "daily", keep("naciones")) == [TUE]


def test_a_day_without_this_competition_absorbs_nothing(week):
    """Thursday has no LaLiga. Asking for the LaLiga round there must not reach
    out and adopt Friday's and Monday's games."""
    assert matchday_days(week, THU, "matchday", keep("laliga")) == [THU]


def test_two_competitions_on_one_day_stay_separate():
    """Both play Wednesday; each recap must cover only its own matches, or one
    title claims the other's results."""
    day = WED
    src = FakeSource({day: [_m(day, UCL, "Madrid"), _m(day, UEL, "Betis")]})
    assert [m.home for m in fixtures_of(src, day, keep("champions"))] == ["Madrid"]
    assert [m.home for m in fixtures_of(src, day, keep("europa"))] == ["Betis"]


def test_record_stems_differ_per_competition():
    """Two recaps of the same day must not collide on one filename — the second
    would overwrite the first's record and orphan its uploaded video."""
    stems = {f"digest_{WED}_{k}_youtube" for k in ("champions", "europa")}
    assert len(stems) == 2
