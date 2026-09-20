"""Spelling the English words so a Spanish voice says them right.

Edge-TTS's neural voices take no SSML <phoneme> and do not code-switch: handed
"League", es-ES-Alvaro reads it with Spanish letter values, and handed "like" —
which every single video says, 162 times across the generated narrations — it
says "LEE-keh". The spelling is the only lever the engine leaves us, so the
audio gets a Spanish spelling that sounds like the English word.

Which means the same text now exists in two forms, and the failure this guards
against is mixing them up: the respelling is for the EAR, and burning "deja tu
laik" into the subtitles would trade a mispronounced word for a misspelled one
in front of the viewer. The tests below pin the split — engine gets one string,
viewer reads the other — and pin the words that must NOT be touched, because a
substitution loose enough to catch "like" is loose enough to eat "liga".
"""

import pytest

from pipeline.voice_generator import _respell_for_speech, _restore_spelling


def _spoken(text):
    return _respell_for_speech(text, "es")


def _subtitle(text):
    """What the viewer reads: the respelled text, run back through restore."""
    return _restore_spelling([{"text": _spoken(text)}])[0]["text"]


# ── The words that get respelled ─────────────────────────────────────
RESPELLS = [
    ("league", "Vivir la Champions League", "Vivir la Champions Lig"),
    ("like", "deja tu like", "deja tu laik"),
    ("likes", "miles de likes", "miles de laiks"),
    ("hat trick", "firmó un hat trick", "firmó un jat trik"),
    ("hat-trick", "firmó un hat-trick", "firmó un jat-trik"),
    ("penalty", "marcó el penalty", "marcó el penalti"),
    ("show", "vaya show", "vaya chou"),
]


@pytest.mark.parametrize("label,text,expected", RESPELLS,
                         ids=[r[0] for r in RESPELLS])
def test_the_engine_is_handed_a_spanish_spelling(label, text, expected):
    assert _spoken(text) == expected


def test_capitalisation_survives():
    """'¡Dale LIKE!' is shouted on purpose — the goal-shout boost counts CAPS
    words to decide how energetic the whole track should be."""
    assert _spoken("¡Dale LIKE ya!") == "¡Dale LAIK ya!"
    assert _spoken("La Champions League") == "La Champions Lig"


# ── What the viewer reads ────────────────────────────────────────────
def test_subtitles_show_the_real_words():
    assert _subtitle("Vive la Champions League y deja tu like.") == \
        "Vive la Champions League y deja tu like."


def test_subtitles_keep_the_spanish_spelling_of_penalti():
    """'penalti' IS the Spanish word, so it is already the right thing to show;
    restoring it to 'penalty' would misspell a Spanish subtitle."""
    assert _subtitle("Marcó el penalty decisivo.") == "Marcó el penalti decisivo."


def test_a_narration_that_already_said_penalti_is_untouched():
    assert _spoken("Marcó de penalti.") == "Marcó de penalti."
    assert _subtitle("Marcó de penalti.") == "Marcó de penalti."


# ── What must never be touched ───────────────────────────────────────
UNTOUCHED = [
    ("liga", "El Racing lidera la Liga."),
    ("ligaba", "El Racing ligaba jugadas."),
    ("ligamento", "Se resintió del ligamento."),
    ("likely-looking Spanish", "Un aliketa no es una palabra, pero no se toca."),
]


@pytest.mark.parametrize("label,text", UNTOUCHED, ids=[u[0] for u in UNTOUCHED])
def test_spanish_words_are_left_alone(label, text):
    assert _spoken(text) == text


def test_english_narrations_are_left_alone():
    """An English voice reading English needs none of this, and applying it
    would break the very words it exists to fix."""
    text = "What a Champions League night — hit that like button."
    assert _respell_for_speech(text, "en") == text
