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
from .video_format import REEL, VideoFormat


def _font_path() -> str | None:
    for p in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(p):
            return p
    return None


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def _subtitle_clips(subtitles: list[dict], total: float, fmt: VideoFormat):
    """MrBeast-style captions: one big BOLD word at a time, thick black outline,
    bright yellow, with a soft pop-in (scale + fade) instead of a hard jump."""
    from moviepy import TextClip

    from .voice_generator import word_cues

    font = _font_path()
    w, h = fmt.width, fmt.height
    base_y = int(h * (0.72 if fmt.vertical else 0.76))
    font_size = int(min(w, h) * 0.072)                   # big, MrBeast-like
    box_h = int(font_size * 2.2)                          # vertical padding
    clips = []
    for cue in word_cues(subtitles):
        start, end = min(cue["start"], total), min(cue["end"], total)
        if end <= start:
            continue
        dur = end - start
        # Bright yellow, THICK black outline for that bold caption look.
        txt = TextClip(
            text=cue["text"].upper(), font=font, font_size=font_size,
            color="#FFE600", stroke_color="black", stroke_width=int(font_size * 0.13),
            method="caption", size=(int(w * 0.92), box_h), text_align="center",
        ).with_start(start).with_duration(dur)

        # Soft pop-in: scale 86%→100% over the first ~18% (no bounce), plus a
        # short fade-in. Smooth and clean.
        def _scale(t, _d=dur):
            prog = min(t / max(_d * 0.18, 0.01), 1.0)
            return 0.86 + 0.14 * _ease_out(prog)

        from moviepy.video.fx import CrossFadeIn
        txt = (txt.resized(_scale)
               .with_position(("center", base_y))
               .with_effects([CrossFadeIn(min(0.15, dur * 0.4))]))
        clips.append(txt)
    return clips


def assemble(cfg: BrandProfile, match: Match, images: list[Path],
             audio_path: Path, subtitles: list[dict], metadata: dict,
             fmt: VideoFormat = REEL) -> Path:
    """Render the .mp4 and return its path.

    Animated broadcast graphics (crowd backdrop + crests + scoreboard + goal/card
    timeline) form the base; the crowd image is composited inside each frame
    (robust — no MoviePy masks), with narration audio and karaoke subtitles on top.
    The output dimensions follow `fmt` (reel 9:16 or youtube 16:9).
    """
    from moviepy import AudioFileClip, CompositeVideoClip

    from .animated_graphics import build_animated_clips, set_format
    set_format(fmt)

    audio = AudioFileClip(str(audio_path))
    total = float(audio.duration)

    # Crowd backdrop image (filename contains "ambience"), composited into the
    # graphics frames themselves rather than layered separately.
    ambience = [p for p in images if "ambience" in p.name]
    backdrop = str(ambience[0]) if ambience else None

    # Place the scoreboard then the timeline back to back WITHOUT a crossfade:
    # the crowd backdrop is baked into every frame, so a crossfade would show
    # black during the overlap. Butt-joining keeps the image whole all the time.
    anim = build_animated_clips(cfg, match, total, background=backdrop)
    graph = []
    cursor = 0.0
    seg_len = total / max(len(anim), 1)
    for clip in anim:
        graph.append(clip.with_start(cursor))
        cursor += seg_len

    layers = [*graph, *_subtitle_clips(subtitles, total, fmt)]
    video = CompositeVideoClip(layers, size=(fmt.width, fmt.height)).with_audio(audio)

    out = cfg.VIDEO_DIR / f"match_{match.fixture_id}.mp4"
    video.write_videofile(
        str(out), fps=24, codec="libx264", audio_codec="aac", logger=None,
    )
    audio.close()
    video.close()
    return out
