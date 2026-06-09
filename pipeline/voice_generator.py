"""
voice_generator.py — synthesize the narration voice and word-timed subtitles.

TTS_PROVIDER:
    edge        Edge-TTS (Microsoft) — FREE, no API key, es-AR/es-ES/es-MX +
                more, supports rate/pitch for excitement and emits subtitles in
                one pass.
    elevenlabs  ElevenLabs — higher quality, needs ELEVEN_LABS* keys in .env;
                uses the with-timestamps endpoint to recover word subtitle cues.
    gtts        gTTS fallback (no subtitles).
    piper       Piper local/offline (no subtitles here).

Returns (audio_path, subtitles) where subtitles is a list of
{start, end, text} cues (seconds) usable for burned-in or SRT subtitles.
"""

import asyncio
import re
from pathlib import Path

from core.brand_config import BrandProfile


def _collapse_stretched(text: str) -> str:
    """Collapse a stretched letter (3+ repeats) down to a single one.

    'GOOOL' / 'GOOOOOL' -> 'GOL', 'golazooo' -> 'golazo', 'siiiii' -> 'si'. The
    TTS voices (especially ElevenLabs) stumble when they try to hold a drawn-out
    vowel, so we say a clean 'gol'. Only 3+ repeats are collapsed, so legitimate
    Spanish double letters ('carro', 'perro', 'llegar') are left untouched.
    Subtitles use the raw text; only the spoken audio is normalised.
    """
    return re.sub(r"(.)\1{2,}", r"\1", text)


def _is_high_energy(text: str) -> bool:
    """True when the narration reads like an excited shout (many CAPS / '¡!')."""
    shouts = text.count("¡") + text.count("!")
    caps_words = sum(1 for w in text.split() if len(w) > 2 and w.isupper())
    return shouts >= 4 or caps_words >= 3


def _bump(pct: str, by: int) -> str:
    """Increase a '+18%' rate string by `by` percentage points."""
    try:
        n = int(pct.replace("%", "").replace("+", "") or 0)
    except ValueError:
        n = 0
    return f"{n + by:+d}%"


def _bump_hz(hz: str, by: int) -> str:
    """Increase a '+12Hz' pitch string by `by` Hz."""
    try:
        n = int(hz.replace("Hz", "").replace("+", "") or 0)
    except ValueError:
        n = 0
    return f"{n + by:+d}Hz"


def _edge(text: str, voice: str, rate: str, audio_path: Path,
          pitch: str = "+0Hz", volume: str = "+12%") -> list[dict]:
    import edge_tts

    cues: list[dict] = []

    async def run():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                           volume=volume)
        with open(audio_path, "wb") as f:
            async for chunk in communicate.stream():
                # Newer edge-tts emits SentenceBoundary; older ones WordBoundary.
                # Both carry offset/duration in 100-nanosecond ticks.
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] in ("SentenceBoundary", "WordBoundary"):
                    start = chunk["offset"] / 1e7
                    dur = chunk["duration"] / 1e7
                    cues.append({"start": start, "end": start + dur,
                                 "text": chunk["text"],
                                 "granularity": chunk["type"]})

    asyncio.run(run())
    return cues


def _gtts(text: str, language: str, audio_path: Path) -> list[dict]:
    from gtts import gTTS
    gTTS(text=text, lang=language).save(str(audio_path))
    return []


def _eleven_keys() -> list[str]:
    """All ELEVEN_LABS* keys from the environment, in declaration order."""
    import os
    keys = []
    for name, val in os.environ.items():
        if name.upper().startswith("ELEVEN_LABS") and val.strip():
            keys.append((name, val.strip()))
    keys.sort(key=lambda kv: kv[0])  # ELEVEN_LABS, ELEVEN_LABS2, ...
    return [v for _, v in keys]


def _elevenlabs(text: str, voice_id: str, audio_path: Path,
                model: str = "eleven_multilingual_v2") -> list[dict]:
    """ElevenLabs TTS with character-level timestamps -> word subtitle cues.

    Tries each ELEVEN_LABS* key in turn so a key that is out of quota (or, for
    library voices, on the free tier -> 402) rolls over to the next one. Premade
    voices (Adam, Bill) work on the free tier; library voices need a paid plan.
    """
    import base64
    import json
    import urllib.error
    import urllib.request

    keys = _eleven_keys()
    if not keys:
        raise RuntimeError("No ELEVEN_LABS* API key in environment / .env")

    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8,
                           "style": 0.6, "use_speaker_boost": True},
    }).encode()
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
           f"/with-timestamps")

    last_err = None
    for key in keys:
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "xi-api-key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                payload = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            last_err = f"{e.code} {e.read()[:200].decode('utf-8', 'replace')}"
            continue
    else:
        raise RuntimeError(f"ElevenLabs request failed on all keys: {last_err}")

    audio_path.write_bytes(base64.b64decode(payload["audio_base64"]))

    # Build word-level cues from per-character timestamps.
    align = payload.get("alignment") or {}
    chars = align.get("characters") or []
    starts = align.get("character_start_times_seconds") or []
    ends = align.get("character_end_times_seconds") or []
    cues: list[dict] = []
    word, w_start = "", None
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if word:
                cues.append({"start": w_start, "end": en, "text": word,
                             "granularity": "WordBoundary"})
                word, w_start = "", None
        else:
            if w_start is None:
                w_start = st
            word += ch
    if word and w_start is not None:
        cues.append({"start": w_start, "end": ends[-1] if ends else w_start,
                     "text": word, "granularity": "WordBoundary"})
    return cues


def synthesize(cfg: BrandProfile, text: str, name: str = "narration") -> tuple[Path, list[dict]]:
    """Synthesize narration audio + subtitle cues for a profile.

    `name` lets callers (e.g. the daily digest) write distinct files per segment
    so concurrent/sequential segments don't overwrite each other's audio.
    """
    audio_path = cfg.IMAGE_DIR.parent / f"{name}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    # Normalise stretched letters (GOOOL -> GOL) so the voice sounds natural.
    text = _collapse_stretched(text)

    rate, pitch = cfg.TTS_RATE, getattr(cfg, "TTS_PITCH", "+0Hz")
    # Goal-shout boost: Edge-TTS has no emotional styles, so when the narration
    # is full of shouts (¡GOL!, lots of CAPS/exclamations) lift the whole
    # track's energy a notch — it reads more like a real play-by-play.
    if _is_high_energy(text):
        rate = _bump(rate, 6)
        pitch = _bump_hz(pitch, 6)

    provider = cfg.TTS_PROVIDER
    if provider == "edge":
        cues = _edge(text, cfg.TTS_VOICE, rate, audio_path, pitch=pitch)
    elif provider == "elevenlabs":
        # ElevenLabs has no SSML prosody, so the goal-shout boost above doesn't
        # apply; the emotion comes from the voice itself.
        model = getattr(cfg, "TTS_MODEL", "eleven_multilingual_v2")
        cues = _elevenlabs(text, cfg.TTS_VOICE, audio_path, model=model)
    elif provider == "gtts":
        cues = _gtts(text, cfg.LANGUAGE, audio_path)
    else:  # piper or unknown -> try edge as the safe default
        cues = _edge(text, cfg.TTS_VOICE, rate, audio_path, pitch=pitch)

    # Sentence-level cues are already readable lines; only word-level cues
    # need grouping into ~8-word subtitle lines.
    if cues and cues[0].get("granularity") == "SentenceBoundary":
        subtitles = [{"start": c["start"], "end": c["end"], "text": c["text"]} for c in cues]
    elif cues:
        subtitles = _group_cues(cues)
    else:
        subtitles = []
    return audio_path, subtitles


def word_cues(subtitles: list[dict]) -> list[dict]:
    """Split sentence cues into per-word cues for karaoke-style captions.

    Edge-TTS no longer emits WordBoundary, so we distribute each sentence's
    duration across its words proportionally to word length (a good visual
    approximation for one-word-at-a-time, jumping subtitles).
    """
    words = []
    for cue in subtitles:
        toks = cue["text"].split()
        if not toks:
            continue
        span = max(cue["end"] - cue["start"], 0.01)
        weights = [len(t) + 1 for t in toks]
        wsum = sum(weights)
        t = cue["start"]
        for tok, w in zip(toks, weights, strict=True):
            dur = span * (w / wsum)
            words.append({"start": t, "end": t + dur, "text": tok})
            t += dur
    return words


def _group_cues(word_cues: list[dict], words_per_line: int = 8) -> list[dict]:
    lines = []
    for i in range(0, len(word_cues), words_per_line):
        chunk = word_cues[i:i + words_per_line]
        lines.append({
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
            "text": " ".join(c["text"] for c in chunk),
        })
    return lines


def write_srt(subtitles: list[dict], dest: Path) -> Path:
    """Write subtitles to an .srt file (also useful for YouTube captions)."""
    def ts(seconds: float) -> str:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, cue in enumerate(subtitles, 1):
        lines.append(str(i))
        lines.append(f"{ts(cue['start'])} --> {ts(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest
