"""
voices.py — named voice presets for the narrator (Edge-TTS).

Broadcaster voices the frontend can offer. Each preset bundles the Edge-TTS
voice id plus rate/pitch tuned for an energetic sports-commentary feel.
Edge-TTS has no emotional styles (Azure-only), so the energy comes from a Latin
voice + raised prosody + an extra boost on goal shouts (see voice_generator).
The Latin male voices (Jorge MX, Tomás AR) carry the play-by-play best.
"""

VOICES = {
    "relator_mx": {
        "label": "Relator · Español MX (Jorge)",
        "voice": "es-MX-JorgeNeural",
        "rate": "+18%", "pitch": "+12Hz", "language": "es",
    },
    "relator_ar": {
        "label": "Relator · Español AR (Tomás)",
        "voice": "es-AR-TomasNeural",
        "rate": "+18%", "pitch": "+12Hz", "language": "es",
    },
    "es_male": {
        "label": "Hombre · Español ES (Álvaro)",
        "voice": "es-ES-AlvaroNeural",
        "rate": "+16%", "pitch": "+8Hz", "language": "es",
    },
    "es_female": {
        "label": "Mujer · Español",
        "voice": "es-ES-ElviraNeural",
        "rate": "+10%", "pitch": "+6Hz", "language": "es",
    },
    "en_male": {
        "label": "Hombre · Inglés (announcer)",
        "voice": "en-US-GuyNeural",
        "rate": "+10%", "pitch": "+6Hz", "language": "en",
    },
    "en_female": {
        "label": "Mujer · Inglés",
        "voice": "en-US-JennyNeural",
        "rate": "+8%", "pitch": "+4Hz", "language": "en",
    },
}

DEFAULT = "relator_mx"


def get(key: str) -> dict:
    return VOICES.get(key, VOICES[DEFAULT])


def options() -> list[dict]:
    """List for the frontend dropdown: [{key, label, language}]."""
    return [{"key": k, "label": v["label"], "language": v["language"]}
            for k, v in VOICES.items()]
