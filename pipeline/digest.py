"""
digest.py — build a DAILY digest video covering all of a day's finished matches.

Each match becomes a short segment (~20-25s) with its own crowd backdrop (the
winning team's colours), animated scoreboard + goal timeline, a tight
play-by-play narration and karaoke subtitles. Segments are concatenated with
smooth crossfades. Two formats:
  reel    — vertical 9:16, capped at ~3 minutes (so ~6 matches fit).
  youtube — horizontal 16:9, 5-8 minutes with longer per-match narration.

Reuses narrator, team-coloured media_provider, animated_graphics and Edge-TTS.
"""

import json
import time
from collections.abc import Callable

from core.brand_config import BrandProfile

from .match_monitor import Match
from .narrator import build_tags, narrate
from .video_format import get_format

StepCb = Callable[[str, str], None]
CancelCb = Callable[[], bool]

# Per-format limits.
_REEL_MAX_MATCHES = 6    # 6 x ~28s ≈ under 3 minutes
_REEL_MAX_SEG = 28       # hard cap per segment (seconds)
_YT_MAX_SEG = 90         # generous cap for the long format


def _segment_clip(cfg, match: Match, narration: str, fmt, seg_cap: float, on_step):
    """Build one match segment: voiced animated graphics over the winner crowd.

    The audio (and thus the segment) is hard-capped at `seg_cap` seconds so the
    whole digest stays within its target length.
    """
    from moviepy import AudioFileClip, CompositeVideoClip

    from .animated_graphics import build_animated_clips, set_format
    from .media_provider import build_visuals
    from .video_assembler import _subtitle_clips
    from .voice_generator import synthesize

    set_format(fmt)
    images = build_visuals(cfg, match, fmt=fmt, on_step=on_step)
    backdrop = str(images[0]) if images else None
    audio_path, subtitles = synthesize(cfg, narration, name=f"seg_{match.fixture_id}")
    audio = AudioFileClip(str(audio_path))
    total = min(float(audio.duration), seg_cap)
    if audio.duration > seg_cap:
        audio = audio.subclipped(0, seg_cap)

    # Butt-join scoreboard + timeline (no crossfade) so the crowd backdrop, baked
    # into every frame, stays whole — no black flash between scenes.
    anim = build_animated_clips(cfg, match, total, background=backdrop)
    graph, cursor, seg = [], 0.0, total / max(len(anim), 1)
    for clip in anim:
        graph.append(clip.with_start(cursor))
        cursor += seg
    layers = [*graph, *_subtitle_clips(subtitles, total, fmt)]
    return CompositeVideoClip(layers, size=(fmt.width, fmt.height)).with_audio(audio), total


def run_daily_digest(profile_id: str, day: str, video_format: str = "reel", *,
                     on_step: StepCb = lambda *_: None,
                     check_cancel: CancelCb = lambda: False) -> dict:
    """Generate a digest of all finished matches on `day`. Returns a result dict."""
    from moviepy import concatenate_videoclips

    from .data_sources import get_data_source

    cfg = BrandProfile(profile_id)
    fmt = get_format(video_format)
    source = get_data_source(cfg)

    on_step("fetch", f"Fetching {day} matches")
    finished = [m for m in source.fixtures_on(day) if m.is_finished]
    if not finished:
        return {"status": "empty", "message": f"No finished matches on {day}"}

    # Cap how many matches fit for the reel (3 min / 25s ≈ 6).
    if fmt.key == "reel":
        finished = finished[:_REEL_MAX_MATCHES]
    style = "digest_short" if fmt.key == "reel" else "digest_long"
    seg_cap = _REEL_MAX_SEG if fmt.key == "reel" else _YT_MAX_SEG

    segments, used, all_tags = [], [], []
    for i, m in enumerate(finished):
        if check_cancel():
            return {"status": "cancelled"}
        full = source.fixture(m.fixture_id)          # enrich goals/cards
        on_step("segment", f"{i + 1}/{len(finished)}: {full.scoreline}")
        narration = narrate(full, language=cfg.LANGUAGE,
                            system_preamble=cfg.system_preamble,
                            provider=cfg.LLM_PROVIDER, style=style)
        clip, dur = _segment_clip(cfg, full, narration, fmt, seg_cap, on_step)
        segments.append(clip)
        used.append({"scoreline": full.scoreline, "duration": round(dur, 1)})
        all_tags += build_tags(full)

    on_step("video", "Stitching the digest")
    # Direct cut between segments (no crossfade): each segment carries its own
    # crowd backdrop, so a crossfade would briefly show black. A hard cut keeps
    # every frame's image whole.
    digest = concatenate_videoclips(segments, method="compose")

    out = cfg.VIDEO_DIR / f"digest_{day}_{fmt.key}.mp4"
    digest.write_videofile(str(out), fps=24, codec="libx264", audio_codec="aac",
                          logger=None)
    for s in segments:
        s.close()
    digest.close()

    # Dedup tags preserving order.
    seen, tags = set(), []
    for t in all_tags:
        if t and t not in seen:
            seen.add(t)
            tags.append(t)

    record = {
        "type": "digest", "day": day, "format": fmt.key,
        "matches": used, "video": str(out), "tags": tags,
        "duration": round(float(digest.duration) if hasattr(digest, "duration") else 0, 1),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    rec_path = cfg.CONTENT_DIR / f"digest_{day}_{fmt.key}.json"
    rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    on_step("done", f"Digest ready: {len(used)} matches")
    return {**record, "status": "done"}
