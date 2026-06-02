"""
voices.py — named voice presets for the narrator (Edge-TTS).

Four professional broadcaster voices the frontend can offer: male/female in
Spanish and English. Each preset bundles the Edge-TTS voice id and a speech
rate tuned for an energetic sports-commentary feel.
"""

VOICES = {
    "es_male": {
        "label": "Hombre · Español (locutor)",
        "voice": "es-ES-AlvaroNeural",
        "rate": "+12%",
        "language": "es",
    },
    "es_female": {
        "label": "Mujer · Español",
        "voice": "es-ES-ElviraNeural",
        "rate": "+10%",
        "language": "es",
    },
    "en_male": {
        "label": "Hombre · Inglés (announcer)",
        "voice": "en-US-GuyNeural",
        "rate": "+10%",
        "language": "en",
    },
    "en_female": {
        "label": "Mujer · Inglés",
        "voice": "en-US-JennyNeural",
        "rate": "+8%",
        "language": "en",
    },
}

DEFAULT = "es_male"


def get(key: str) -> dict:
    return VOICES.get(key, VOICES[DEFAULT])


def options() -> list[dict]:
    """List for the frontend dropdown: [{key, label, language}]."""
    return [{"key": k, "label": v["label"], "language": v["language"]}
            for k, v in VOICES.items()]
