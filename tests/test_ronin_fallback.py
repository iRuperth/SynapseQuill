"""Pairing the two Rōnin sources, and naming what they report.

Everything here fails SILENTLY if it regresses — nothing raises, a video is just
published that should not have been, or is not published at all:

  · the backup not filling in    -> the club's whole season goes unnoticed, which
                                    is the bug this pairing was written for
  · the backup NOT stepping back -> the same match filmed twice under two ids,
                                    because the scheduler's processed-set keys on
                                    the id and cannot see they are one game
  · a competition name unmatched -> the video publishes as #Futbol instead of
                                    #RoninFC, or is titled with the wrong division

The two sources spell things differently on purpose in these fixtures, because
they really do: the acta URL says "tercera-catalana", the community site says
"3ª Catalana.".
"""

from core import competitions
from pipeline.data_sources.base import FootballDataSource
from pipeline.data_sources.fallback import FallbackSource
from pipeline.match_monitor import Match

DAY = "2026-09-20"          # Rōnin's first fixture of 2026/27, in Tercera
OTHER = "2026-09-27"


def _m(fixture_id: str, day: str = DAY, status: str = "FT",
       competition: str = "3ª Catalana.") -> Match:
    return Match(fixture_id=fixture_id, status=status,
                 home="Rōnin FC", away="La Romànica",
                 home_goals=2 if status == "FT" else None,
                 away_goals=0 if status == "FT" else None,
                 competition=competition, date=day)


class _Fake(FootballDataSource):
    """A source holding exactly the matches it is given."""

    def __init__(self, name: str, matches: list[Match]):
        self.name = name
        self.matches = matches

    def fixtures_on(self, day: str | None = None) -> list[Match]:
        return [m for m in self.matches if m.date == day]

    def latest_finished(self, limit: int = 10) -> list[Match]:
        return [m for m in self.matches if m.is_finished][:limit]

    def fixture(self, fixture_id):
        return next(m for m in self.matches if str(m.fixture_id) == str(fixture_id))


def _pair(primary: list[Match], backup: list[Match]) -> FallbackSource:
    return FallbackSource(_Fake("fcf", primary), _Fake("ronindigital", backup))


# ── the backup filling in ────────────────────────────────────────────────
def test_backup_covers_a_day_the_acta_source_knows_nothing_about():
    """The whole reason this exists: on 4 Sep 2026 roninfc.fans held nothing of
    the new season while the community site had the full calendar."""
    feed = _pair([], [_m("match-1")])
    got = feed.fixtures_on(DAY)
    assert len(got) == 1
    # Namespaced so fixture() can route the lookup back to the right source.
    assert str(got[0].fixture_id) == "ronindigital-match-1"


def test_acta_source_wins_when_it_has_the_day():
    """The acta carries scorers, minutes and cards; the backup carries none of
    them. Whenever both have the match, the richer one is the one narrated."""
    feed = _pair([_m("acta-9")], [_m("match-1")])
    got = feed.fixtures_on(DAY)
    assert [str(m.fixture_id) for m in got] == ["acta-9"]


def test_acta_source_keeps_a_day_it_has_only_scheduled():
    """A fixture listed but not yet played still belongs to the acta source: its
    report is worth waiting a few hours for, and the backup jumping in would
    publish the poorer video first and block the richer one for good."""
    feed = _pair([_m("acta-9", status="NS")], [_m("match-1")])
    assert [str(m.fixture_id) for m in feed.fixtures_on(DAY)] == ["acta-9"]


# ── the duplicate that would otherwise be published ──────────────────────
def test_a_day_already_served_by_the_backup_is_never_reclaimed():
    """The dangerous ordering: the backup supplies the result, the video goes
    out, and only THEN does roninfc.fans publish its acta for the same game.

    The two sources give it different ids, so the scheduler's processed-set sees
    a match it has never handled and films it again — a second public upload of
    a game already on the channel. Nothing raises; it just happens.
    """
    primary = _Fake("fcf", [])
    feed = FallbackSource(primary, _Fake("ronindigital", [_m("match-1")]))

    served = feed.fixtures_on(DAY)                  # video generated from this
    assert [str(m.fixture_id) for m in served] == ["ronindigital-match-1"]

    primary.matches = [_m("acta-9")]                # roninfc.fans wakes up late
    again = feed.fixtures_on(DAY)
    assert [str(m.fixture_id) for m in again] == ["ronindigital-match-1"]


def test_stepping_back_is_per_day_not_wholesale():
    """One day taken over by the backup must not hand it every other day too."""
    primary = _Fake("fcf", [_m("acta-7", day=OTHER)])
    feed = FallbackSource(primary, _Fake("ronindigital", [_m("match-1")]))
    feed.fixtures_on(DAY)                            # backup takes DAY
    assert [str(m.fixture_id) for m in feed.fixtures_on(OTHER)] == ["acta-7"]


# ── routing and resilience ───────────────────────────────────────────────
def test_fixture_lookup_routes_to_the_source_that_issued_the_id():
    feed = _pair([_m("acta-9")], [_m("match-1")])
    assert str(feed.fixture("acta-9").fixture_id) == "acta-9"
    assert str(feed.fixture("ronindigital-match-1").fixture_id) == "ronindigital-match-1"


def test_one_dead_source_does_not_take_the_other_down():
    """Both are small community sites. Either can be unreachable, and the club
    disappearing from the channel because one of them 500s is the failure this
    pairing is supposed to remove, not introduce."""

    class _Dead(FootballDataSource):
        name = "fcf"

        def fixtures_on(self, day=None):
            raise RuntimeError("unreachable")

        def latest_finished(self, limit=10):
            raise RuntimeError("unreachable")

        def fixture(self, fixture_id):
            raise RuntimeError("unreachable")

    feed = FallbackSource(_Dead(), _Fake("ronindigital", [_m("match-1")]))
    assert len(feed.fixtures_on(DAY)) == 1


# ── naming: both sources must land on the same preset ────────────────────
def test_both_sources_name_the_same_competition_the_same_way():
    """The acta URL and the community site disagree on spelling; a video's
    hashtags and title must not depend on which one happened to answer."""
    for reported in ("Tercera Catalana", "3ª Catalana.", "3ª Catalana. Jornada 1"):
        assert competitions.key_for(reported) == "tercera_catalana"
        assert competitions.tags_for(reported) == ["#RoninFC", "#TerceraCatalana"]


def test_each_tier_is_named_as_itself():
    """These were one preset whose Spanish name was the literal 'Tercera
    Catalana', so a Quarta Catalana match was titled as Tercera. The club is
    climbing, which is exactly when that goes stale, and the division is a fact
    stated in a published title."""
    assert competitions.of_name_es("4ª Catalana. Jornada 30") == "de la Cuarta Catalana"
    assert competitions.of_name_es("Quarta Catalana") == "de la Cuarta Catalana"
    assert competitions.of_name_es("3ª Catalana.") == "de la Tercera Catalana"


def test_a_pre_season_friendly_is_not_tagged_generic_football():
    """Matched as whole words, so the site's plural "Partidos Amistosos" does
    NOT match the alias "amistoso" and would fall through to #Futbol."""
    assert competitions.tags_for("Partidos Amistosos") == ["#RoninFC", "#Pretemporada"]
    # ESPN's national-team friendlies must still resolve to their own preset.
    assert competitions.key_for("International Friendly") == "amistosos"


# ── the recap that would duplicate the match video ───────────────────────
def test_single_club_competitions_get_no_round_recap():
    """Rōnin plays one match a week and every one of them is filmed. A "jornada"
    recap of that competition would hold exactly that match — a second upload of
    a video already on the channel."""
    for reported in ("3ª Catalana.", "Tercera Catalana", "Copa Catalunya",
                     "Partidos Amistosos"):
        assert not competitions.has_round_up(reported)


def test_multi_club_competitions_keep_their_recap():
    """The recap is how the channel covers rounds it does NOT film match by
    match; switching it off for those would silently drop most of a cup round."""
    for reported in ("Spanish LALIGA", "UEFA Champions League", "Copa del Rey"):
        assert competitions.has_round_up(reported)
