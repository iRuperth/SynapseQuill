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


def _subtitle_clips(subtitles: list[dict], total: float, fmt: VideoFormat):
    """Karaoke-style captions: one YELLOW word at a time with a jump animation."""
    from moviepy import TextClip

    from .voice_generator import word_cues

    font = _font_path()
    w, h = fmt.width, fmt.height
    base_y = int(h * (0.76 if fmt.vertical else 0.80))   # safe lower band
    font_size = int(min(w, h) * 0.078)
    clips = []
    for cue in word_cues(subtitles):
        start, end = min(cue["start"], total), min(cue["end"], total)
        if end <= start:
            continue
        dur = end - start
        # method="caption" with a fixed width centres the word and wraps long
        # ones, so nothing ever gets clipped at the frame edges.
        txt = TextClip(
            text=cue["text"].upper(), font=font, font_size=font_size,
            color="yellow", stroke_color="black", stroke_width=5,
            method="caption", size=(int(w * 0.92), None), text_align="center",
        ).with_start(start).with_duration(dur)

        # Jump animation: the word pops up a few px then settles (ease-out).
        def _pos(t, _y=base_y, _d=dur):
            prog = min(t / max(_d * 0.4, 0.01), 1.0)
            jump = int(20 * (1 - prog) ** 2)      # small bounce, stays on screen
            return ("center", _y - jump)

        clips.append(txt.with_position(_pos))
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
    from moviepy.video.fx import CrossFadeIn

    from .animated_graphics import build_animated_clips, set_format
    set_format(fmt)

    audio = AudioFileClip(str(audio_path))
    total = float(audio.duration)

    # Crowd backdrop image (filename contains "ambience"), composited into the
    # graphics frames themselves rather than layered separately.
    ambience = [p for p in images if "ambience" in p.name]
    backdrop = str(ambience[0]) if ambience else None

    anim = build_animated_clips(cfg, match, total, background=backdrop)
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

    layers = [*graph, *_subtitle_clips(subtitles, total, fmt)]
    video = CompositeVideoClip(layers, size=(fmt.width, fmt.height)).with_audio(audio)

    out = cfg.VIDEO_DIR / f"match_{match.fixture_id}.mp4"
    video.write_videofile(
        str(out), fps=24, codec="libx264", audio_codec="aac", logger=None,
    )
    audio.close()
    video.close()
    return out
