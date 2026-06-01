"""
video_assembler.py — assemble the final .mp4 from images + narration + subtitles.

Builds a slideshow: each visual is shown for an even slice of the narration
duration with a subtle Ken-Burns zoom, the narration audio underneath and
burned-in subtitles. Mirrors Synapse Core's video_assembler approach, kept
POC-simple.

Targets MoviePy 2.x (no moviepy.editor; with_* methods; Pillow-based TextClip).
Requires ffmpeg (declared in the Dockerfile).
"""

import os
from pathlib import Path

from core.brand_config import BrandProfile

from .match_monitor import Match

W, H = 1280, 720


def _font_path() -> str | None:
    for p in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(p):
            return p
    return None


def _subtitle_clips(subtitles: list[dict], total: float):
    from moviepy import TextClip

    font = _font_path()
    clips = []
    for cue in subtitles:
        start, end = min(cue["start"], total), min(cue["end"], total)
        if end <= start:
            continue
        txt = TextClip(
            text=cue["text"], font=font, font_size=38, color="white",
            stroke_color="black", stroke_width=2,
            method="caption", size=(int(W * 0.9), None),
        ).with_start(start).with_duration(end - start).with_position(("center", H - 140))
        clips.append(txt)
    return clips


def assemble(cfg: BrandProfile, match: Match, images: list[Path],
             audio_path: Path, subtitles: list[dict], metadata: dict) -> Path:
    """Render the .mp4 and return its path."""
    from moviepy import (
        AudioFileClip,
        CompositeVideoClip,
        ImageClip,
        concatenate_videoclips,
    )
    from moviepy.video.fx import CrossFadeIn, FadeIn, FadeOut

    audio = AudioFileClip(str(audio_path))
    total = float(audio.duration)
    per = total / max(len(images), 1)
    fade = min(0.6, per / 3)          # smooth crossfade between slides

    slides = []
    for i, img in enumerate(images):
        # Full-frame static image (no zoom): fit to the canvas, centred.
        clip = (ImageClip(str(img))
                .resized(width=W)
                .with_duration(per)
                .with_position("center"))
        # Crossfade-in on every slide except the first; gentle fades at the ends.
        if i == 0:
            clip = clip.with_effects([FadeIn(0.4)])
        else:
            clip = clip.with_effects([CrossFadeIn(fade)])
        slides.append(clip)

    base = (concatenate_videoclips(slides, method="compose", padding=-fade)
            .with_duration(total)
            .with_effects([FadeOut(0.5)]))
    layers = [base, *_subtitle_clips(subtitles, total)]
    video = CompositeVideoClip(layers, size=(W, H)).with_audio(audio)

    out = cfg.VIDEO_DIR / f"match_{match.fixture_id}.mp4"
    video.write_videofile(
        str(out), fps=24, codec="libx264", audio_codec="aac", logger=None,
    )
    audio.close()
    video.close()
    return out
