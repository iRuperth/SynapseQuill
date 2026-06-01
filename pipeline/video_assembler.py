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

# Reels / Shorts format: vertical 9:16.
W, H = 1080, 1920


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
            text=cue["text"], font=font, font_size=52, color="white",
            stroke_color="black", stroke_width=3,
            method="caption", size=(int(W * 0.9), None),
            bg_color=(0, 0, 0, 140),               # readable band behind text (RGBA)
            text_align="center",
        ).with_start(start).with_duration(end - start).with_position(("center", H - 520))
        clips.append(txt)
    return clips


def assemble(cfg: BrandProfile, match: Match, images: list[Path],
             audio_path: Path, subtitles: list[dict], metadata: dict) -> Path:
    """Render the .mp4 and return its path.

    The base layer is animated broadcast-style motion graphics (scoreboard +
    goal timeline). Any FLUX ambience images are shown briefly as an intro/cover
    behind a fade. Narration audio and readable subtitles sit on top.
    """
    from moviepy import (
        AudioFileClip,
        CompositeVideoClip,
        ImageClip,
        concatenate_videoclips,
    )
    from moviepy.video.fx import CrossFadeIn, FadeIn, FadeOut

    from .animated_graphics import build_animated_clips

    audio = AudioFileClip(str(audio_path))
    total = float(audio.duration)

    # Separate FLUX ambience images (filename contains "ambience") from data
    # cards; the animated graphics replace the static data cards entirely.
    ambience = [p for p in images if "ambience" in p.name]

    segments = []
    # Optional short ambience intro (first ~22% of the video) if available.
    intro_t = 0.0
    if ambience:
        intro_t = min(total * 0.22, 3.0)
        cover = (ImageClip(str(ambience[0]))
                 .resized(width=W)
                 .with_duration(intro_t)
                 .with_position("center")
                 .with_effects([FadeIn(0.4)]))
        segments.append(cover)

    # Animated graphics fill the rest.
    graph_total = max(total - intro_t, 0.1)
    anim = build_animated_clips(cfg, match, graph_total)
    fade = 0.5
    for i, clip in enumerate(anim):
        segments.append(clip.with_effects([CrossFadeIn(fade)]) if (i or intro_t) else clip)

    base = (concatenate_videoclips(segments, method="compose", padding=-fade)
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
