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
    """Karaoke-style captions: one YELLOW word at a time with a jump animation."""
    from moviepy import TextClip

    from .voice_generator import word_cues

    font = _font_path()
    base_y = H - 360             # bottom area, clear of the scoreboard/timeline
    clips = []
    for cue in word_cues(subtitles):
        start, end = min(cue["start"], total), min(cue["end"], total)
        if end <= start:
            continue
        dur = end - start
        # method="caption" with a fixed width centres the word and wraps long
        # ones, so nothing ever gets clipped at the frame edges.
        txt = TextClip(
            text=cue["text"].upper(), font=font, font_size=84,
            color="yellow", stroke_color="black", stroke_width=5,
            method="caption", size=(int(W * 0.92), None), text_align="center",
        ).with_start(start).with_duration(dur)

        # Jump animation: the word pops up a few px then settles (ease-out).
        def _pos(t, _y=base_y, _d=dur):
            prog = min(t / max(_d * 0.4, 0.01), 1.0)
            jump = int(40 * (1 - prog) ** 2)      # starts +40px up, settles
            return ("center", _y - jump)

        clips.append(txt.with_position(_pos))
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
        ColorClip,
        CompositeVideoClip,
        ImageClip,
    )
    from moviepy.video.fx import CrossFadeIn

    from .animated_graphics import build_animated_clips

    audio = AudioFileClip(str(audio_path))
    total = float(audio.duration)

    # ── Background: crowd/stadium ambience fills the WHOLE video (no more empty
    # black space). Darkened so the graphics and subtitles stay readable.
    ambience = [p for p in images if "ambience" in p.name]
    if ambience:
        bg = (ImageClip(str(ambience[0]))
              .resized((W, H))
              .with_duration(total))
        dim = (ColorClip(size=(W, H), color=(8, 12, 24))
               .with_opacity(0.55)
               .with_duration(total))
        bg_layers = [bg, dim]
    else:
        bg_layers = [ColorClip(size=(W, H), color=(11, 16, 32)).with_duration(total)]

    # ── Animated graphics (transparent) layered over the crowd.
    anim = build_animated_clips(cfg, match, total)
    fade = 0.5
    graph = []
    cursor = 0.0
    seg_len = total / max(len(anim), 1)
    for i, clip in enumerate(anim):
        c = clip.with_start(cursor)
        if i > 0:
            c = c.with_effects([CrossFadeIn(fade)])
        graph.append(c)
        cursor += seg_len

    layers = [*bg_layers, *graph, *_subtitle_clips(subtitles, total)]
    video = CompositeVideoClip(layers, size=(W, H)).with_audio(audio)

    out = cfg.VIDEO_DIR / f"match_{match.fixture_id}.mp4"
    video.write_videofile(
        str(out), fps=24, codec="libx264", audio_codec="aac", logger=None,
    )
    audio.close()
    video.close()
    return out
