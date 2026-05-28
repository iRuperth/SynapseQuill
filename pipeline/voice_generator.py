"""
voice_generator.py — synthesize the narration voice and word-timed subtitles.

TTS_PROVIDER:
    edge   Edge-TTS (Microsoft) — FREE, no API key, es-AR/es-ES/es-MX + more,
           supports rate/pitch for excitement and emits subtitles in one pass.
    gtts   gTTS fallback (no subtitles).
    piper  Piper local/offline (no subtitles here).

Returns (audio_path, subtitles) where subtitles is a list of
{start, end, text} cues (seconds) usable for burned-in or SRT subtitles.
"""

import asyncio
from pathlib import Path

from core.brand_config import BrandProfile


def _edge(text: str, voice: str, rate: str, audio_path: Path) -> list[dict]:
    import edge_tts

    cues: list[dict] = []

    async def run():
        communicate = edge_tts.Communicate(text, voice, rate=rate)
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


def synthesize(cfg: BrandProfile, text: str) -> tuple[Path, list[dict]]:
    """Synthesize narration audio + subtitle cues for a profile."""
    audio_path = cfg.IMAGE_DIR.parent / "narration.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    provider = cfg.TTS_PROVIDER
    if provider == "edge":
        cues = _edge(text, cfg.TTS_VOICE, cfg.TTS_RATE, audio_path)
    elif provider == "gtts":
        cues = _gtts(text, cfg.LANGUAGE, audio_path)
    else:  # piper or unknown -> try edge as the safe default
        cues = _edge(text, cfg.TTS_VOICE, cfg.TTS_RATE, audio_path)

    # Sentence-level cues are already readable lines; only word-level cues
    # need grouping into ~8-word subtitle lines.
    if cues and cues[0].get("granularity") == "SentenceBoundary":
        subtitles = [{"start": c["start"], "end": c["end"], "text": c["text"]} for c in cues]
    elif cues:
        subtitles = _group_cues(cues)
    else:
        subtitles = []
    return audio_path, subtitles


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
