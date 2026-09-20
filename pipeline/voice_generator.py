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


# English words a Spanish narration carries anyway, and how to spell them so a
# Spanish voice says them right. Edge-TTS's neural voices accept no SSML
# <phoneme> and do not code-switch: es-ES-Alvaro reads "League" with Spanish
# letter values ("le-a-gu-e") and "like" as "LEE-keh". Since the engine gives us
# no other lever, the spelling IS the lever — hand it a Spanish spelling that
# sounds like the English word.
#
# Earned its place by frequency, not by guesswork: "like" appears 162 times
# across the generated narrations (every video ends with "deja tu like") and
# "League" in every Champions and Europa League recap.
#
# Proper nouns are deliberately absent. A stadium or a player's name is a rabbit
# hole with no correct answer — "Signal Iduna Park" has no Spanish spelling that
# is more right than the current one — and a bad guess there is worse than the
# accent it replaces.
_ES_RESPELL = {
    "league": "lig",
    "like": "laik",
    "likes": "laiks",
    "hat-trick": "jat-trik",
    "hat trick": "jat trik",
    "penalty": "penalti",
    "penalties": "penaltis",
    "show": "chou",
}

# Respellings that must NOT reach the subtitles: "lig" and "laik" are spoken
# spellings, not words, and burning them into the video would trade a
# mispronounced word for a misspelled one. "penalti" is missing on purpose —
# it is the real Spanish word, so it is already the right thing to SHOW.
_SPEECH_ONLY = {"lig", "laik", "laiks", "jat-trik", "jat trik", "chou"}

# Longest first so "hat trick" wins over a bare "hat", and word-bounded so
# "liga" and "aliketa" are never touched.
_RESPELL_ALT = "|".join(re.escape(k) for k in
                        sorted(_ES_RESPELL, key=len, reverse=True))
_RESPELL_RE = re.compile(rf"\b(?:{_RESPELL_ALT})\b", re.IGNORECASE)
_RESTORE = {v: k for k, v in _ES_RESPELL.items() if v in _SPEECH_ONLY}
_RESTORE_ALT = "|".join(re.escape(k) for k in
                        sorted(_RESTORE, key=len, reverse=True))
_RESTORE_RE = re.compile(rf"\b(?:{_RESTORE_ALT})\b", re.IGNORECASE)


def _match_case(sample: str, word: str) -> str:
    """Give `word` the capitalisation `sample` was written with, so a shouted
    '¡Dale LIKE!' stays shouted and 'Champions League' keeps its capital."""
    if sample.isupper() and len(sample) > 1:
        return word.upper()
    if sample[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def _respell_for_speech(text: str, language: str) -> str:
    """Rewrite the English words above with Spanish spellings, for the AUDIO.

    Spanish only: an English voice reading an English narration needs none of
    this, and applying it there would break the words it is meant to fix.
    """
    if not (language or "").lower().startswith("es"):
        return text
    return _RESPELL_RE.sub(
        lambda m: _match_case(m.group(0), _ES_RESPELL[m.group(0).lower()]), text)


def _restore_spelling(cues: list[dict]) -> list[dict]:
    """Put the real words back into the subtitle cues.

    The TTS engines derive their cue text from the string we HAND them, so
    without this the burned-in subtitles would read "deja tu laik".
    """
    for c in cues:
        c["text"] = _RESTORE_RE.sub(
            lambda m: _match_case(m.group(0), _RESTORE[m.group(0).lower()]),
            c.get("text", ""))
    return cues


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
    # Spanish spellings for the English words the narration carries, so the
    # voice says "lig" and "laik" rather than reading them as Spanish. NOT for
    # ElevenLabs: its multilingual model code-switches on its own, so handing it
    # a phonetic spelling would break a word it already pronounces correctly.
    if provider != "elevenlabs":
        spoken = _respell_for_speech(text, cfg.LANGUAGE)
    else:
        spoken = text

    if provider == "edge":
        cues = _edge(spoken, cfg.TTS_VOICE, rate, audio_path, pitch=pitch)
    elif provider == "elevenlabs":
        # ElevenLabs has no SSML prosody, so the goal-shout boost above doesn't
        # apply; the emotion comes from the voice itself.
        model = getattr(cfg, "TTS_MODEL", "eleven_multilingual_v2")
        cues = _elevenlabs(spoken, cfg.TTS_VOICE, audio_path, model=model)
    elif provider == "gtts":
        cues = _gtts(spoken, cfg.LANGUAGE, audio_path)
    else:  # piper or unknown -> try edge as the safe default
        cues = _edge(spoken, cfg.TTS_VOICE, rate, audio_path, pitch=pitch)

    # The cues came back spelled the way the ENGINE was fed; the viewer must
    # read the real words.
    cues = _restore_spelling(cues)

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
