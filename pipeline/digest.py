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


# Crossfade overlap between match segments (seconds). Each segment starts this
# long before the previous one ends, so during the overlap we see the outgoing
# crowd dissolve INTO the incoming one — image over image, never a black flash.
_XFADE = 0.6


def _stitch_with_crossfade(segments: list):
    """Concatenate match segments with a smooth crossfade between them. Segments
    overlap by `_XFADE`; each (except the first) fades its video and audio in
    over the overlap, so the transition is a soft dissolve with no black gap."""
    from moviepy import CompositeVideoClip
    from moviepy.audio.fx import AudioFadeIn, AudioFadeOut
    from moviepy.video.fx import CrossFadeIn

    if len(segments) <= 1:
        return CompositeVideoClip(segments) if segments else segments[0]

    placed, t = [], 0.0
    for i, seg in enumerate(segments):
        if i == 0:
            placed.append(seg.with_start(0))
            t = seg.duration
            continue
        start = t - _XFADE
        clip = seg.with_start(start).with_effects([CrossFadeIn(_XFADE)])
        # Soft-fade the audio too so the narration/music don't cut abruptly.
        if clip.audio is not None:
            clip = clip.with_audio(
                clip.audio.with_effects([AudioFadeIn(_XFADE), AudioFadeOut(_XFADE)]))
        placed.append(clip)
        t = start + seg.duration
    return CompositeVideoClip(placed)


def _matchday_window(source, day: str, on_step) -> list:
    """All finished matches of the JORNADA around `day`. A league round is played
    across consecutive days (Fri-Mon) and games that start late cross midnight,
    so a single calendar day misses half the round. We gather a small window of
    days around `day` and dedupe by fixture id."""
    from datetime import date as _d
    from datetime import timedelta
    try:
        y, mo, dd = (int(x) for x in day.split("-"))
        center = _d(y, mo, dd)
    except (ValueError, AttributeError):
        return [m for m in source.fixtures_on(day) if m.is_finished]
    seen, out = set(), []
    # 3 days before .. 1 day after covers a weekend round even across midnight.
    for delta in range(-3, 2):
        d = (center + timedelta(days=delta)).isoformat()
        on_step("fetch", f"Fetching matchday around {d}")
        for m in source.fixtures_on(d):
            if m.is_finished and m.fixture_id not in seen:
                seen.add(m.fixture_id)
                out.append(m)
    out.sort(key=lambda m: (m.date or "", m.kickoff or ""))
    return out


def run_daily_digest(profile_id: str, day: str, video_format: str = "reel", *,
                     fixture_ids: list | None = None, brief: str = "",
                     upload: bool | None = None,
                     on_step: StepCb = lambda *_: None,
                     check_cancel: CancelCb = lambda: False) -> dict:
    """Generate a digest video. By default it covers the whole matchday (jornada)
    around `day`; pass `fixture_ids` to include only those matches. `brief` is a
    free-form angle ('the most exciting World Cup ties') woven into the intro and
    outro. `upload` forces the YouTube upload on/off; None defers to the
    profile's AUTO_UPLOAD. Returns a result dict."""
    from .data_sources import get_data_source

    cfg = BrandProfile(profile_id)
    fmt = get_format(video_format)
    source = get_data_source(cfg)

    if fixture_ids:
        # Manual selection: just the chosen matches (any day), in the given order.
        on_step("fetch", f"Fetching {len(fixture_ids)} selected matches")
        wanted = {int(f) for f in fixture_ids}
        finished = [source.fixture(fid) for fid in fixture_ids]
        finished = [m for m in finished if m and m.is_finished and m.fixture_id in wanted]
    else:
        # Automatic: the whole matchday around `day`.
        finished = _matchday_window(source, day, on_step)
    if not finished:
        return {"status": "empty", "message": f"No finished matches for {day}"}

    # Cap how many matches fit for the reel (3 min / 25s ≈ 6). The horizontal
    # youtube digest has no cap — it covers every match of the round.
    if fmt.key == "reel":
        finished = finished[:_REEL_MAX_MATCHES]
    style = "digest_short" if fmt.key == "reel" else "digest_long"
    seg_cap = _REEL_MAX_SEG if fmt.key == "reel" else _YT_MAX_SEG

    segments, used, all_tags = [], [], []
    last_i = len(finished) - 1
    for i, m in enumerate(finished):
        if check_cancel():
            return {"status": "cancelled"}
        full = source.fixture(m.fixture_id)          # enrich goals/cards
        on_step("segment", f"{i + 1}/{len(finished)}: {full.scoreline}")
        # The brief (e.g. "the most exciting World Cup ties") frames the digest:
        # it opens the FIRST segment and closes the LAST one.
        narration = narrate(full, language=cfg.LANGUAGE,
                            system_preamble=cfg.system_preamble,
                            provider=cfg.LLM_PROVIDER, style=style,
                            digest_brief=brief, digest_open=(i == 0),
                            digest_close=(i == last_i))
        # Make each segment sound human (e.g. "la penalty" -> "el penalty").
        from .text_polish import polish
        narration = polish(narration, language=cfg.LANGUAGE, provider=cfg.LLM_PROVIDER)
        clip, dur = _segment_clip(cfg, full, narration, fmt, seg_cap, on_step)
        segments.append(clip)
        used.append({"scoreline": full.scoreline, "duration": round(dur, 1)})
        all_tags += build_tags(full)

    on_step("video", "Stitching the digest")
    digest = _stitch_with_crossfade(segments)

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

    # Upload the finished digest when forced by the caller (the scheduler) or
    # when the profile has auto-upload enabled. Privacy comes from the profile
    # (YOUTUBE_PRIVACY, default private; PRACTICE_MODE forces private).
    if cfg.AUTO_UPLOAD if upload is None else upload:
        on_step("upload", f"Uploading digest to YouTube ({cfg.YOUTUBE_PRIVACY})")
        title = f"Resumen del día · {day}"
        # Real text as the description — the uploader appends the hashtags
        # itself, so putting the tags here would print them twice (spam wall).
        scorelines = "\n".join(u["scoreline"] for u in used)
        meta = {"title": title,
                "description": f"Todos los resultados de la jornada:\n{scorelines}",
                "tags": tags}
        try:
            from .publishers import upload_youtube
            record["youtube_url"] = upload_youtube(cfg, out, meta)
            record["youtube_privacy"] = cfg.YOUTUBE_PRIVACY
        except Exception as e:  # noqa: BLE001
            on_step("upload", f"Auto-upload failed: {e}")
            record["upload_error"] = str(e)

    rec_path = cfg.CONTENT_DIR / f"digest_{day}_{fmt.key}.json"
    rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    on_step("done", f"Digest ready: {len(used)} matches")
    return {**record, "status": "done"}
