"""
voices.py — named voice presets for the narrator.

Broadcaster voices the frontend can offer. Each preset bundles a TTS `provider`
plus a voice id and prosody. Two providers are supported:

  edge        Edge-TTS (Microsoft) — FREE, no key, rate/pitch drive the energy
              (no emotional styles), with an extra boost on goal shouts (see
              voice_generator). The Latin males (Jorge MX, Tomás AR) carry the
              play-by-play best.
  elevenlabs  ElevenLabs — higher quality, needs ELEVEN_LABS* keys in .env. The
              `voice` is an ElevenLabs voice id; for premade voices it can be
              read from an env var (see ELEVEN_VOICE_* in .env). Library voices
              (e.g. a custom "Theo") require a PAID ElevenLabs plan; premade
              voices (Adam, Bill) work on the free tier.

A preset with no `provider` key defaults to edge. ElevenLabs presets ignore
rate/pitch (ElevenLabs has no SSML prosody knobs) but keep them as no-ops.
"""

import os

VOICES = {
    "relator_mx": {
        "label": "Relator · Español MX (Jorge)",
        "voice": "es-MX-JorgeNeural",
        # Jorge MX is the most expressive Spanish male voice on Edge-TTS, so we
        # push the prosody for a euphoric play-by-play feel ("Jorge medio").
        # The goal-shout boost in voice_generator stacks on top of this.
        "rate": "+26%", "pitch": "+20Hz", "language": "es",
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
    "relator_es": {
        "label": "Relator · Español ES (Álvaro, eufórico)",
        "voice": "es-ES-AlvaroNeural",
        # Same España male voice as `es_male` but pushed for a lively,
        # play-by-play feel: faster and higher than the plain `es_male`, so the
        # baseline narration already sounds upbeat — not just the goal shouts.
        # Edge-TTS exposes no emotional styles, so energy comes from prosody;
        # the goal-shout boost in voice_generator stacks on top of this.
        "rate": "+26%", "pitch": "+18Hz", "language": "es",
    },
    "es_female": {
        "label": "Locutora · Español ES (Elvira)",
        "voice": "es-ES-ElviraNeural",
        # Raised prosody for an energetic play-by-play feel.
        "rate": "+16%", "pitch": "+10Hz", "language": "es",
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
    # --- ElevenLabs (premade voices; work on the free tier) ----------------
    # The voice ids live in .env (ELEVEN_VOICE_ADAM / ELEVEN_VOICE_BILL) so all
    # ElevenLabs configuration stays in one place; `get()` resolves the env var
    # and falls back to the hard-coded premade id if it is unset.
    "el_adam": {
        "label": "ElevenLabs · Adam (premade)",
        "provider": "elevenlabs",
        "voice_env": "ELEVEN_VOICE_ADAM",
        "voice": "pNInz6obpgDQGcFmaJgB",
        "model": "eleven_multilingual_v2",
        "rate": "+0%", "pitch": "+0Hz", "language": "es",
    },
    "el_bill": {
        "label": "ElevenLabs · Bill (premade)",
        "provider": "elevenlabs",
        "voice_env": "ELEVEN_VOICE_BILL",
        "voice": "pqHfZKP75CvOlQylNhV4",
        "model": "eleven_multilingual_v2",
        "rate": "+0%", "pitch": "+0Hz", "language": "es",
    },
}

DEFAULT = "relator_mx"


def get(key: str) -> dict:
    """Return a preset, resolving any env-backed voice id (ElevenLabs)."""
    preset = dict(VOICES.get(key, VOICES[DEFAULT]))
    env_key = preset.get("voice_env")
    if env_key:
        preset["voice"] = os.getenv(env_key) or preset["voice"]
    preset.setdefault("provider", "edge")
    return preset


def options() -> list[dict]:
    """List for the frontend dropdown: [{key, label, language}]."""
    return [{"key": k, "label": v["label"], "language": v["language"]}
            for k, v in VOICES.items()]
