"""How a narration is allowed to state the final score.

The deterministic score check is the one gate that cannot be argued with: if it
says the final was never stated, the video is held back and nobody publishes it.
That makes a FALSE FAILURE expensive in a way that is easy to miss — a correct
Racing de Santander 2-1 Alaves recap sat rendered on disk while the LLM judge,
reading the same sentence, called it fully grounded, because the check only
recognised digits either side of one separator and the narrator had written the
score the way a commentator says it out loud: "Racing de Santander 2, Alaves 1",
with the club names in between.

So both directions are pinned here. The forms a Spanish narration actually uses
must PASS, and every way a wrong final could sneak through must still FAIL —
because the cure for a false failure is a looser pattern, and a loose pattern
that pairs any two nearby digits would read a scoreline out of "al 62" and "un
57 por ciento" and wave through a narration that never stated the score at all.
"""

import pytest

from agents.guardrail import facts_check
from pipeline.match_monitor import Match


def _match(home="Racing Santander", away="Alavés", hg=2, ag=1):
    return Match(fixture_id="laliga-401882881", status="FT", home=home,
                 away=away, home_goals=hg, away_goals=ag)


def _score_issues(match, text):
    """Only the score complaints — this module has no opinion on the rest."""
    return [i for i in facts_check(match, text, "es")["issues"]
            if "final score" in i or "last score stated" in i]


# ── Forms that must be accepted ──────────────────────────────────────
STATED = [
    # The form that caused this: club names between the two digits.
    ("teams between digits", "Final en El Sardinero: Racing de Santander 2, Alavés 1."),
    # The forms that already worked, kept here so a rewrite cannot drop them.
    ("hyphen", "Final: Racing Santander 2-1 Alavés."),
    ("colon", "Final: Racing Santander 2:1 Alavés."),
    ("a", "Final: Racing Santander 2 a 1 Alavés."),
    ("word form", "Final: Racing Santander dos a uno Alavés."),
    # A running score first, the real final last: the ORDER rule must read the
    # anchored final as the last one stated, not the 1-1 before it.
    ("running then final",
     "Racing 1, Alavés 1 al descanso. Al final: Racing de Santander 2, Alavés 1."),
    # Minutes and percentages sit right next to the score in every real
    # narration and must not be mistaken for one.
    ("minutes nearby",
     "Al 62 apretaba y al 88 llegó la roja. Final: Racing 2, Alavés 1."),
    ("possession nearby",
     "El Racing dominó con un 57 por ciento. Final: Racing 2, Alavés 1."),
]


@pytest.mark.parametrize("label,text", STATED, ids=[s[0] for s in STATED])
def test_score_forms_that_must_pass(label, text):
    assert _score_issues(_match(), text) == []


def test_the_real_racing_narration_passes():
    """The exact sentence that was held back, verbatim."""
    text = ("Y en el 53, Zabiri vuelve a aparecer y la clava al centro: "
            "¡GOOOL, doblete! ¡Remontada en marcha, Racing 2, Alavés 1! "
            "Final en El Sardinero: Racing de Santander 2, Alavés 1.")
    assert _score_issues(_match(), text) == []


# ── Everything that must still be caught ─────────────────────────────
def test_no_score_at_all_is_still_caught():
    text = "Un partido intensísimo. El Racing acabó celebrando en su casa."
    assert _score_issues(_match(), text) == ["final score 2-1 not clearly stated"]


def test_a_wrong_anchored_final_is_still_caught():
    """The looser pattern must not become a way to state the WRONG score."""
    text = "Final: Racing de Santander 3, Alavés 1."
    assert _score_issues(_match(), text) == ["final score 2-1 not clearly stated"]


def test_a_running_score_after_the_final_is_still_caught():
    text = ("Final: Racing de Santander 2, Alavés 1. "
            "Antes de eso, el Alavés se había puesto 0-1.")
    assert _score_issues(_match(), text) == [
        "the last score stated (0-1) is not the final 2-1"]


def test_digits_far_apart_are_not_a_score():
    """Two clubs and two numbers in one paragraph are not a scoreline."""
    text = ("El Racing ha marcado 2 goles en sus últimas visitas al Sardinero, "
            "un dato que no dice demasiado sobre lo que se vio hoy, y el "
            "Alavés 1 sola vez ha ganado en este estadio.")
    assert _score_issues(_match(), text) == ["final score 2-1 not clearly stated"]


# ── Clubs whose names make the anchoring hard ────────────────────────
def test_clubs_sharing_a_word_still_anchor():
    """'Real' identifies neither side of Real Madrid v Real Sociedad, so the
    anchoring has to fall back on the word that does."""
    m = _match("Real Madrid", "Real Sociedad", 3, 0)
    assert _score_issues(m, "Final: Real Madrid 3, Real Sociedad 0.") == []


def test_a_club_whose_only_word_looks_generic():
    """'Sociedad', 'Deportivo' and 'Sporting' read like filler and are the only
    distinctive word those clubs have; filtering them would leave no anchor."""
    m = _match("Sporting Gijón", "Deportivo La Coruña", 2, 0)
    assert _score_issues(
        m, "Final: Sporting de Gijón 2, Deportivo de La Coruña 0.") == []


def test_a_draw_is_reported_readably():
    """A 1-1 used to be reported as 'the last score stated (1)', which reads
    like a bug to the human being asked to review the hold."""
    m = _match("Athletic Club", "Elche", 1, 1)
    assert _score_issues(m, "Final: Athletic Club 1, Elche 1. Antes iban 2-0.") == [
        "the last score stated (2-0) is not the final 1-1"]
