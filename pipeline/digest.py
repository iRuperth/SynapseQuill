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
import os
import time
from collections.abc import Callable

from core import competitions
from core.brand_config import BrandProfile

from .match_monitor import Match
from .narrator import _scoreline_es, build_digest_tags, narrate
from .video_format import get_format

StepCb = Callable[[str, str], None]
CancelCb = Callable[[], bool]

# Per-format limits.
_REEL_MAX_MATCHES = 6    # 6 x ~28s ≈ under 3 minutes
# Ceiling for the long horizontal recap. It used to have none, which was fine
# while the channel carried one league: a full LaLiga jornada is 10 matches. A
# cup round is not — the Copa del Rey opens with 25 ties on a single Wednesday,
# and at up to 90s each that is a 35-minute video nobody watches to the end.
# 12 clears a whole jornada with room to spare.
_YT_MAX_MATCHES = 12
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
        # Soft-fade the audio too so the narration doesn't cut abruptly. Only
        # the narration: the music bed is composited over the finished stitch
        # further down, so it is deliberately NOT subject to these joins.
        if clip.audio is not None:
            clip = clip.with_audio(
                clip.audio.with_effects([AudioFadeIn(_XFADE), AudioFadeOut(_XFADE)]))
        placed.append(clip)
        t = start + seg.duration
    return CompositeVideoClip(placed)


# How far either side of `day` a league round can reach. A LaLiga jornada opens
# Friday and closes Monday, so three days of slack on each side covers it while
# still stopping at the empty midweek that separates two rounds.
_MATCHDAY_REACH = 3


def fixtures_of(source, day: str, keep=None) -> list:
    """Fixtures on `day`, optionally narrowed to one competition.

    `keep` is a predicate over a Match. Everything that reasons about rounds goes
    through here, because on a merged feed "the fixtures on this day" and "the
    fixtures of THIS COMPETITION on this day" are different questions and only
    the second one delimits a round.
    """
    fixtures = source.fixtures_on(day) or []
    return [m for m in fixtures if keep(m)] if keep else list(fixtures)


def matchday_days(source, day: str, mode: str = "matchday", keep=None) -> list[str]:
    """The calendar days that make up the round `day` belongs to, ascending.

    mode="daily"    — the calendar day IS the round. The World Cup plays every
                      day, so its 3-4 fixtures make one recap.
    mode="matchday" — a league jornada spans several days (LaLiga: Friday to
                      Monday). Treating each day as its own round would chop one
                      jornada into three thin recaps that each claim to be "la
                      jornada", so we walk outwards from `day` while consecutive
                      days still have fixtures and stop at the first empty one —
                      the midweek gap that separates rounds.

    `keep` restricts which fixtures count, and on a multi-competition channel it
    is REQUIRED for the walk to mean anything. The empty day it stops at is the
    midweek gap in ONE competition's calendar; a feed carrying LaLiga (Fri-Mon)
    plus the Champions League (Tue-Wed) plus the Europa League (Thu) has no empty
    day left in the week, so an unfiltered walk would swallow all seven days and
    call the result "la jornada".

    The FIRST element is the round's anchor: every day of a round resolves to the
    same list, so callers can key a round by days[0] and build it exactly once.
    """
    from datetime import date as _date
    from datetime import timedelta

    if mode == "daily":
        return [day]
    try:
        d0 = _date.fromisoformat(day)
    except ValueError:
        return [day]
    # A day with no fixtures belongs to no round. Without this it would still
    # absorb its neighbours and anchor a round on an empty midweek day, and that
    # round would then be built a SECOND time under its real first day.
    if not fixtures_of(source, day, keep):
        return [day]

    days = {day}
    for step in (-1, 1):                        # backwards, then forwards
        for n in range(1, _MATCHDAY_REACH + 1):
            d = (d0 + timedelta(days=step * n)).isoformat()
            if not fixtures_of(source, d, keep):
                break                           # empty day -> edge of the round
            days.add(d)
    return sorted(days)


def _matchday_window(source, day: str, on_step, *, mode: str = "matchday",
                     keep=None) -> list:
    """All finished matches of the round `day` belongs to, deduped by fixture id
    and ordered by kickoff so the recap follows the round."""
    days = matchday_days(source, day, mode, keep)
    on_step("fetch", f"Fetching matches on {', '.join(days)}")
    seen, out = set(), []
    for d in days:
        for m in fixtures_of(source, d, keep):
            if m.is_finished and m.fixture_id not in seen:
                seen.add(m.fixture_id)
                out.append(m)
    out.sort(key=lambda m: (m.date or "", m.kickoff or ""))
    return out


# Spanish month names for a human-readable digest title, indexed 1-12.
_MONTHS_ES = ("", "enero", "febrero", "marzo", "abril", "mayo", "junio",
              "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")

def _readable_day(day: str) -> str:
    """ISO date '2026-06-11' -> '11 de junio de 2026'. Falls back to the raw
    string if the date is malformed, so the title is never empty."""
    try:
        y, mo, dd = (int(x) for x in day.split("-"))
        return f"{dd} de {_MONTHS_ES[mo]} de {y}"
    except (ValueError, IndexError, AttributeError):
        return day


def _readable_day_dm(day: str) -> str:
    """ISO date '2026-06-11' -> '11 de junio' (no year). Used in titles that
    already state the year elsewhere, to avoid repeating it."""
    try:
        _y, mo, dd = (int(x) for x in day.split("-"))
        return f"{dd} de {_MONTHS_ES[mo]}"
    except (ValueError, IndexError, AttributeError):
        return day


def _digest_title(day: str, competition: str = "") -> str:
    """Generic YouTube title for the round's recap, e.g. 'Resumen de la jornada
    del 15 de agosto de LaLiga'. The competition is named from its preset, so
    the title follows whatever the channel covers; an unknown competition simply
    drops the suffix rather than claiming the wrong one."""
    head = f"Resumen de la jornada del {_readable_day_dm(day)}"
    tail = competitions.of_name_es(competition)
    return f"{head} {tail}" if tail else head


def run_daily_digest(profile_id: str, day: str, video_format: str = "reel", *,
                     fixture_ids: list | None = None, brief: str = "",
                     upload: bool | None = None, competition: str = "",
                     on_step: StepCb = lambda *_: None,
                     check_cancel: CancelCb = lambda: False) -> dict:
    """Generate a digest video. By default it covers the whole matchday (jornada)
    around `day`; pass `fixture_ids` to include only those matches. `brief` is a
    free-form angle ('the most exciting World Cup ties') woven into the intro and
    outro. `upload` forces the YouTube upload on/off; None defers to the
    profile's AUTO_UPLOAD.

    `competition` scopes the recap to ONE competition (a preset key, e.g.
    "champions"), which is what a channel carrying several of them needs: the
    round is delimited by that competition's own calendar, and the title, the
    hashtags and the record's name all come from it rather than from the
    channel. Left empty, the recap covers the whole feed and takes the channel's
    identity — the single-competition behaviour, unchanged.

    Returns a result dict."""
    from .data_sources import get_data_source

    cfg = BrandProfile(profile_id)
    fmt = get_format(video_format)
    source = get_data_source(cfg)
    # Identity of THIS recap: the named competition when there is one, else the
    # channel's. Everything user-visible below reads from `ident`.
    ident = competition or cfg.COMPETITION
    keep = None
    if competition:
        want = competitions.key_for(competition) or competition
        keep = lambda m: competitions.key_for(m.competition) == want  # noqa: E731
    # Suffix keeping two competitions' recaps of the same day in separate files.
    # Without it the second one to finish would overwrite the first's record and
    # orphan its uploaded video.
    stem = f"digest_{day}_{competition}_{fmt.key}" if competition else f"digest_{day}_{fmt.key}"

    if fixture_ids:
        # Manual selection: just the chosen matches (any day), in the given order.
        on_step("fetch", f"Fetching {len(fixture_ids)} selected matches")
        # Compared as strings: a merged feed namespaces ids ("laliga-401882920"),
        # so int() would raise on every id the LaLiga + Rōnin channel serves.
        wanted = {str(f) for f in fixture_ids}
        finished = [source.fixture(fid) for fid in fixture_ids]
        finished = [m for m in finished
                    if m and m.is_finished and str(m.fixture_id) in wanted]
    else:
        # Automatic: the whole matchday around `day`. How wide that is depends
        # on the competition — a league jornada spans Friday to Monday, a World
        # Cup day is its own round.
        finished = _matchday_window(source, day, on_step,
                                    mode=competitions.digest_mode(ident),
                                    keep=keep)
    if not finished:
        return {"status": "empty", "message": f"No finished matches for {day}"}

    # Cap how many matches fit (3 min / 25s ≈ 6 for the reel; see _YT_MAX_MATCHES
    # for the long cut). Say so out loud when it bites: a recap that silently
    # drops half a cup round still calls itself the round's recap.
    cap = _REEL_MAX_MATCHES if fmt.key == "reel" else _YT_MAX_MATCHES
    if len(finished) > cap:
        on_step("fetch", f"{len(finished)} matches in this round — covering the "
                         f"first {cap}, leaving out {len(finished) - cap}")
        finished = finished[:cap]
    style = "digest_short" if fmt.key == "reel" else "digest_long"
    seg_cap = _REEL_MAX_SEG if fmt.key == "reel" else _YT_MAX_SEG

    segments, used, digest_matches = [], [], []
    failed_segments = []                          # scorelines that never passed
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
        # Same guardrail as single-match videos — a digest segment is published
        # prose too. Retry with the failed checks fed back (3 attempts max).
        from agents.guardrail import verify
        verdict = verify(full, narration, cfg.LANGUAGE,
                         judge_provider=cfg.JUDGE_PROVIDER,
                         judge_model=cfg.JUDGE_MODEL)
        for attempt in range(2):
            if verdict["passed"]:
                break
            reasons = "; ".join(verdict["facts"]["issues"]) or \
                verdict.get("judge", {}).get("reason", "")
            on_step("guardrail", f"Segment rejected ({reasons}) — "
                                 f"retrying ({attempt + 2}/3)")
            narration = narrate(full, language=cfg.LANGUAGE,
                                system_preamble=cfg.system_preamble +
                                f"\nBe strictly factual. A previous draft was "
                                f"rejected for: {reasons}. Copy every name, "
                                "card colour and goal type EXACTLY.",
                                provider=cfg.LLM_PROVIDER, style=style,
                                digest_brief=brief, digest_open=(i == 0),
                                digest_close=(i == last_i))
            verdict = verify(full, narration, cfg.LANGUAGE,
                             judge_provider=cfg.JUDGE_PROVIDER,
                             judge_model=cfg.JUDGE_MODEL)
        if not verdict["passed"]:
            failed_segments.append(full.scoreline)
            on_step("guardrail", f"WARNING: '{full.scoreline}' still failing "
                                 "after 3 attempts — baked in; review before publishing")
        # Make each segment sound human (e.g. "la penalty" -> "el penalty"),
        # then re-check the facts: a polish that broke one is discarded.
        from .narrator import players_left_count
        from .text_polish import polish
        polished = polish(narration, language=cfg.LANGUAGE, provider=cfg.LLM_PROVIDER,
                          players_left=players_left_count(full))
        if polished != narration and verify(full, polished, cfg.LANGUAGE,
                                            use_judge=False)["passed"]:
            narration = polished
        clip, dur = _segment_clip(cfg, full, narration, fmt, seg_cap, on_step)
        segments.append(clip)
        used.append({"scoreline": full.scoreline, "duration": round(dur, 1)})
        digest_matches.append(full)

    on_step("video", "Stitching the digest")
    digest = _stitch_with_crossfade(segments)

    # Background music, laid over the WHOLE stitched digest rather than per
    # segment. Two reasons for doing it here: a per-segment bed would restart
    # the track every 28-90s, and _stitch_with_crossfade already fades each
    # segment's audio in and out at the joins, which would chop the music into
    # audibly separate pieces instead of one continuous bed.
    # The bed is FLAT (peak == base), like assemble_plain: the reel swells on
    # goal shouts using that segment's own subtitle timings, and those are local
    # to each segment — reusing them here would need every cue re-offset to its
    # position in the stitched timeline. A steady bed under a 6-7 minute recap
    # is the right call anyway.
    # _background_music loops a track shorter than the digest and trims a longer
    # one, so this holds whatever MUSIC_TRACK points at.
    if digest.audio is not None:
        from moviepy import CompositeAudioClip

        from .video_assembler import _background_music
        base = float(os.getenv("MUSIC_VOLUME", "0.08"))
        music = _background_music(float(digest.duration), [], base, base)
        if music is not None:
            on_step("music", "Laying the background music bed")
            digest = digest.with_audio(CompositeAudioClip([music, digest.audio]))

    out = cfg.VIDEO_DIR / f"{stem}.mp4"
    digest.write_videofile(str(out), fps=24, codec="libx264", audio_codec="aac",
                          logger=None)
    for s in segments:
        s.close()
    digest.close()

    # Digest hashtags: a minimal <competition> + #Resumen stack (#LaLiga for a
    # league round, #FIFAWorldCup #Mundial2026 for a World Cup day), led by a
    # format-specific reach tag — #Shorts for the vertical reel cut, #Highlights
    # for the horizontal long cut (YouTube ignores #Shorts on a non-vertical
    # video, and #Highlights is what people search for full recaps).
    tags = build_digest_tags(ident, is_short=(fmt.key == "reel"))

    # Build the publish metadata NOW, not inside the upload branch below. A
    # digest generated with uploads off is meant to be published later by hand,
    # and upload_content() falls back to a generic "Resumen del día · <day>"
    # when the record carries none — a DAY title on what is deliberately a
    # ROUND recap spanning Friday to Monday. Storing it here means the manual
    # upload publishes exactly what the automatic one would have.
    # Real text as the description: the uploader appends the hashtags itself,
    # so repeating them here would print them twice (a spam wall).
    scorelines = "\n".join(_scoreline_es(u["scoreline"]) for u in used)
    meta = {"title": _digest_title(day, ident),
            "description": f"Todos los resultados de la jornada:\n{scorelines}",
            "tags": tags}

    record = {
        "type": "digest", "day": day, "format": fmt.key,
        "competition": competition,
        "matches": used, "video": str(out), "tags": tags,
        "metadata": meta,
        "duration": round(float(digest.duration) if hasattr(digest, "duration") else 0, 1),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "failed_segments": failed_segments,
    }

    # Upload the finished digest when forced by the caller (the scheduler) or
    # when the profile has auto-upload enabled. Privacy comes from the profile
    # (YOUTUBE_PRIVACY, default private; PRACTICE_MODE forces private).
    # GATE: an AUTO upload (upload is None -> AUTO_UPLOAD) is skipped when any
    # segment failed its guardrail; an explicit upload=True (a human asked) is
    # honoured. The video and record are kept either way for manual review.
    #
    # This gate only covers the INLINE upload below, and on this channel that
    # upload never happens: AUTO_UPLOAD is False because publishing belongs to
    # the separate uploader process. So skip_auto cannot fire here and never
    # set upload_skipped — the real gate for a digest is hold_reasons() in
    # upload_manager.py, which reads `failed_segments` from the record written
    # just above. Keep that field populated, or a digest carrying a rejected
    # segment publishes itself with nothing in the way.
    auto = upload is None
    skip_auto = auto and cfg.AUTO_UPLOAD and failed_segments
    if skip_auto:
        on_step("upload", f"Skipped auto-upload: {len(failed_segments)} segment(s) "
                          "failed the guardrail — left for manual review")
        record["upload_skipped"] = "guardrail failed"
    elif cfg.AUTO_UPLOAD if upload is None else upload:
        on_step("upload", f"Uploading digest to YouTube ({cfg.YOUTUBE_PRIVACY})")
        try:
            from .publishers import upload_youtube
            record["youtube_url"] = upload_youtube(cfg, out, meta)
            record["youtube_privacy"] = cfg.YOUTUBE_PRIVACY
            # Upload verified: free the local artifacts so an unattended run
            # never fills the disk — the stitched digest .mp4 plus every
            # segment's audio (seg_<id>.mp3) and crowd images. The published
            # video is the source of truth; the record keeps the YouTube URL.
            from .publishers import cleanup_local_artifacts
            artifacts = [out]
            for dm in digest_matches:
                artifacts.append(cfg.IMAGE_DIR.parent / f"seg_{dm.fixture_id}.mp3")
                artifacts.append(cfg.IMAGE_DIR / f"match_{dm.fixture_id}")
            cleanup_local_artifacts(record["youtube_url"], artifacts,
                                    on_step=on_step)
        except Exception as e:  # noqa: BLE001
            on_step("upload", f"Auto-upload failed: {e}")
            record["upload_error"] = str(e)

    rec_path = cfg.CONTENT_DIR / f"{stem}.json"
    rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    on_step("done", f"Digest ready: {len(used)} matches")
    return {**record, "status": "done"}
