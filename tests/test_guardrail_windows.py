"""Which prose counts as evidence about WHICH player.

Both deterministic detectors work the same way: find where a player is named,
read the words around that mention, and complain when they describe the wrong
colour of card or the wrong body part. The window was a flat 90 characters
either side, and 90 characters of football prose reaches straight through a
comma into somebody else's action — so the evidence being read was frequently
about a different player entirely.

Every failure this produced was a FALSE HOLD, and a false hold is invisible: the
video is finished, correct, and simply never appears on the channel. A Getafe
description that says "recibieron amarillos" and "un disparo de derecho" — both
right — was refused on the strength of a sending-off the same sentence
attributes to Romero BY NAME, and of a header the same sentence attributes to
Starfelt by name.

The tests pin the narrowing, and pin what must still be caught with it: a
window that stops at the next player is still the whole clause about this one,
so a genuinely miscoloured card or a genuinely wrong foot has nowhere to hide.
"""

from agents.guardrail import _card_color_issues, _goal_detail_issues
from pipeline.match_monitor import Card, Goal, Match


def _match(goals=(), cards=()):
    return Match(fixture_id="laliga-401882891", status="FT", home="Getafe",
                 away="Celta Vigo", home_goals=1, away_goals=1,
                 goals=list(goals), cards=list(cards))


# ── Cards ────────────────────────────────────────────────────────────
def test_a_neighbours_sending_off_is_not_this_players_red():
    """The exact description that was held back, verbatim."""
    m = _match(cards=[Card(player="Ramón Terrats", team="Getafe", minute="30",
                           color="Yellow"),
                      Card(player="Zaid Romero", team="Getafe", minute="45",
                           color="Red"),
                      Card(player="Johan Mojica", team="Getafe", minute="20",
                           color="Yellow")])
    text = ("Johan Mojica, Zaid Romero y Ramón Terrats recibieron amarillos "
            "para el equipo local, mientras que Romero fue expulsado por doble "
            "tarjeta amarilla.")
    assert _card_color_issues(m, text) == []


def test_plural_amarillos_counts_as_a_yellow():
    """A description booking three players at once writes the masculine plural;
    the pattern only knew 'amarilla' and read that as no yellow evidence."""
    m = _match(cards=[Card(player="Ramón Terrats", team="Getafe", minute="30",
                           color="Yellow")])
    assert _card_color_issues(m, "Ramón Terrats y otros dos recibieron amarillos.") == []


def test_a_genuinely_miscoloured_card_is_still_caught():
    m = _match(cards=[Card(player="Ramón Terrats", team="Getafe", minute="30",
                           color="Yellow")])
    text = "Ramón Terrats fue expulsado con roja directa tras una entrada dura."
    assert _card_color_issues(m, text) == [
        "Ramón Terrats's card is yellow, but the text calls it red"]


# ── Goals ────────────────────────────────────────────────────────────
def test_a_neighbours_header_is_not_this_scorers_body_part():
    m = _match(goals=[Goal(player="Martín Satriano", team="Getafe", minute="20",
                           kind="Normal Goal",
                           description="Right footed shot from the centre of the box"),
                      Goal(player="Carl Starfelt", team="Celta Vigo", minute="60",
                           kind="Normal Goal",
                           description="Header from the centre of the box")])
    text = ("Martín Satriano adelantó al Getafe con un disparo de derecho, pero "
            "Carl Starfelt igualó con un cabezazo tras un córner.")
    assert _goal_detail_issues(m, text) == []


def test_de_derecho_is_a_right_footed_shot():
    """Spanish says both 'de derecha' and 'de derecho' for the same foot; only
    the feminine was listed, so a correct description read as no foot at all."""
    m = _match(goals=[Goal(player="Martín Satriano", team="Getafe", minute="20",
                           kind="Normal Goal",
                           description="Right footed shot from the centre of the box")])
    for phrase in ("un disparo de derecho", "un disparo de derecha"):
        assert _goal_detail_issues(m, f"Martín Satriano marcó con {phrase}.") == []


def test_a_genuinely_wrong_foot_is_still_caught():
    m = _match(goals=[Goal(player="Martín Satriano", team="Getafe", minute="20",
                           kind="Normal Goal",
                           description="Right footed shot from the centre of the box")])
    text = "Martín Satriano marcó con un zurdazo imparable desde la frontal."
    assert _goal_detail_issues(m, text) == [
        "Martín Satriano's goal was a right foot, but the text describes a "
        "different body part"]


def test_a_bare_surname_also_bounds_the_window():
    """A description names a player in full once and by surname after; the
    boundary scan has to recognise both or a neighbour's clause leaks in."""
    m = _match(goals=[Goal(player="Martín Satriano", team="Getafe", minute="20",
                           kind="Normal Goal",
                           description="Right footed shot from the centre of the box"),
                      Goal(player="Carl Starfelt", team="Celta Vigo", minute="60",
                           kind="Normal Goal",
                           description="Header from the centre of the box")])
    text = ("Carl Starfelt rondaba el área. Martín Satriano marcó de derecho y "
            "Starfelt respondió con un cabezazo.")
    assert _goal_detail_issues(m, text) == []
