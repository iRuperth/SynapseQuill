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
    # Vertical (Shorts/Reels): the phone UI covers the top ~9% (status bar),
    # the right ~13% from ~48-82% height (like/share rail) and the bottom ~27%
    # (channel + title overlay) — so captions sit at 62%, above that bottom
    # band, and in a narrower box that clears the rail. Horizontal keeps the
    # classic low band: desktop YouTube draws no permanent overlay there.
    base_y = int(h * (0.62 if fmt.vertical else 0.80))
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
            method="caption", size=(int(w * (0.74 if fmt.vertical else 0.92)), box_h),
            text_align="center",
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


def _goal_windows(subtitles: list[dict]) -> list[tuple[float, float]]:
    """Time windows (start, end) around goal shouts, to swell the music there.

    Looks for 'gol'/'goool' in the subtitle cues and returns a ~3s window around
    each, so the background track lifts right when the narrator screams the goal.
    """
    windows = []
    for cue in subtitles:
        text = (cue.get("text") or "").lower()
        if "gol" in text or "goal" in text:
            start = float(cue.get("start", 0))
            windows.append((max(0.0, start - 0.5), start + 2.5))
    return windows


def _background_music(total: float, n_subs_goals: list[tuple[float, float]],
                      base: float, peak: float):
    """Load the configured music track, loop/trim to `total`, and apply a
    time-varying volume: `base` normally, rising to `peak` during goal windows.

    Returns an AudioClip or None if no track is configured / found.
    """
    import os

    from moviepy import AudioFileClip
    from moviepy.audio.fx import AudioLoop

    track = os.getenv("MUSIC_TRACK", "").strip()
    if not track:
        return None
    path = Path(track)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / track
    if not path.exists():
        print(f"[music] track not found, skipping: {path}")
        return None

    music = AudioFileClip(str(path))
    # Loop the track if it's shorter than the video, then trim to length.
    if music.duration < total:
        music = music.with_effects([AudioLoop(duration=total)])
    music = music.subclipped(0, total)

    def volume_at(t):
        # t may be a scalar or a numpy array (MoviePy passes arrays).
        try:
            import numpy as np
            tt = np.asarray(t, dtype=float)
            vol = np.full(tt.shape, base)
            for (s, e) in n_subs_goals:
                vol = np.where((tt >= s) & (tt <= e), peak, vol)
            return vol
        except Exception:
            for (s, e) in n_subs_goals:
                if s <= float(t) <= e:
                    return peak
            return base

    # Scale each audio sample by the time-varying volume curve.
    def scaler(get_frame, t):
        frame = get_frame(t)
        v = volume_at(t)
        try:
            import numpy as np
            v = np.asarray(v)
            if frame.ndim == 2 and v.ndim == 1:
                v = v[:, None]   # broadcast volume across stereo channels
        except Exception:
            pass
        return frame * v

    return music.transform(scaler, apply_to=["audio"])


def assemble(cfg: BrandProfile, match: Match, images: list[Path],
             audio_path: Path, subtitles: list[dict], metadata: dict,
             fmt: VideoFormat = REEL) -> Path:
    """Render the .mp4 and return its path.

    Animated broadcast graphics (crowd backdrop + crests + scoreboard + goal/card
    timeline) form the base; the crowd image is composited inside each frame
    (robust — no MoviePy masks), with narration audio and karaoke subtitles on top.
    The output dimensions follow `fmt` (reel 9:16 or youtube 16:9).
    """
    from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip

    from .animated_graphics import build_animated_clips, set_format
    set_format(fmt)

    audio = AudioFileClip(str(audio_path))
    total = float(audio.duration)

    # Background music sits WELL BELOW the narration: a quiet bed at 8% that
    # only nudges up to 12% on goals, so the voice always dominates. Tunable via
    # .env (MUSIC_VOLUME / MUSIC_VOLUME_PEAK).
    base = float(os.getenv("MUSIC_VOLUME", "0.08"))
    peak = float(os.getenv("MUSIC_VOLUME_PEAK", "0.12"))
    music = _background_music(total, _goal_windows(subtitles), base, peak)
    if music is not None:
        audio = CompositeAudioClip([music, audio])   # narration on top of music

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


def assemble_plain(cfg: BrandProfile, out_stem: str, backdrop: Path | None,
                   audio_path: Path, subtitles: list[dict],
                   fmt: VideoFormat = REEL) -> Path:
    """Render a topic/educational .mp4: a clean crowd backdrop + pulsing logo,
    narration audio and karaoke subtitles. No scorebug, no match data.

    `out_stem` names the output file (e.g. 'topic_<id>'). `backdrop` may be None,
    in which case the flat brand background is used.
    """
    from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip

    from .animated_graphics import build_plain_clip, set_format
    set_format(fmt)

    audio = AudioFileClip(str(audio_path))
    total = float(audio.duration)

    # Background music sits well below the narration, same as the match path, but
    # with no goal swells (there are no goals) — a steady quiet bed.
    base = float(os.getenv("MUSIC_VOLUME", "0.08"))
    music = _background_music(total, [], base, base)
    if music is not None:
        audio = CompositeAudioClip([music, audio])

    anim = build_plain_clip(total, background=str(backdrop) if backdrop else None)
    layers = [*anim, *_subtitle_clips(subtitles, total, fmt)]
    video = CompositeVideoClip(layers, size=(fmt.width, fmt.height)).with_audio(audio)

    out = cfg.VIDEO_DIR / f"{out_stem}.mp4"
    video.write_videofile(
        str(out), fps=24, codec="libx264", audio_codec="aac", logger=None,
    )
    audio.close()
    video.close()
    return out
