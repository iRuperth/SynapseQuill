"""
runner.py — orchestrates the per-match generation pipeline.

Phase 1 produces the narration + YouTube metadata and writes a content JSON.
Later phases plug in media generation, TTS, video assembly and YouTube upload
behind the same `on_step` / `check_cancel` callback contract used by the API's
background tasks (mirrors Synapse Core's run_pipeline).
"""

import json
import time
from collections.abc import Callable

from core.brand_config import BrandProfile

from .match_monitor import Match
from .narrator import narrate, youtube_metadata

# Optional later-phase modules are imported lazily inside run_match so Phase 1
# works even before they exist.

StepCb = Callable[[str, str], None]      # (step_key, human_message)
CancelCb = Callable[[], bool]


def _noop_step(step: str, msg: str) -> None:
    print(f"[pipeline] {step}: {msg}")


def _noop_cancel() -> bool:
    return False


def run_match(profile_id: str, match: Match, *,
              on_step: StepCb = _noop_step,
              check_cancel: CancelCb = _noop_cancel,
              do_video: bool = True,
              do_upload: bool = False,
              do_social: bool = False,
              video_format: str = "reel") -> dict:
    """Run the full generation for one finished match. Returns a result dict."""
    from .video_format import get_format
    cfg = BrandProfile(profile_id)
    fmt = get_format(video_format)
    result: dict = {"fixture_id": match.fixture_id, "scoreline": match.scoreline}

    # --- 0. Enrich scorers (optional) --------------------------------
    # If the data source gave no goals (e.g. TheSportsDB free for the World Cup),
    # pull scorers + minutes from ESPN so the narration can name them.
    import os
    if not match.goals and os.getenv("ESPN_ENRICH", "true").lower() == "true":
        on_step("enrich", "Fetching scorers from ESPN")
        from .data_sources.espn_enrich import enrich
        match = enrich(cfg, match)
        if match.goals:
            on_step("enrich", f"Added {len(match.goals)} scorer(s) from ESPN")

    # --- 1. Narration -------------------------------------------------
    on_step("narrate", f"Writing narration for {match.scoreline}")
    narration = narrate(match, language=cfg.LANGUAGE,
                        system_preamble=cfg.system_preamble, provider=cfg.LLM_PROVIDER)
    result["narration"] = narration
    if check_cancel():
        return {**result, "status": "cancelled"}

    # --- 1b. Guardrail: verify narration against the real match data --
    on_step("guardrail", "Verifying narration is grounded in match facts")
    from agents.guardrail import verify
    verdict = verify(match, narration, cfg.LANGUAGE, judge_provider=cfg.LLM_PROVIDER)
    result["guardrail"] = verdict
    if not verdict["passed"]:
        # Retry once with a stricter instruction before giving up.
        on_step("guardrail", "Narration failed checks — regenerating once")
        narration = narrate(match, language=cfg.LANGUAGE,
                            system_preamble=cfg.system_preamble + "\nBe strictly factual.",
                            provider=cfg.LLM_PROVIDER)
        result["narration"] = narration
        result["guardrail"] = verify(match, narration, cfg.LANGUAGE,
                                     judge_provider=cfg.LLM_PROVIDER)

    # --- 1c. Polish: make the script sound human (editor crew) -------
    # Fix known Spanish slips deterministically (e.g. "la penalty" -> "el
    # penalty") and let an LLM editor rewrite anything that still reads
    # unnaturally — WITHOUT changing facts. Then re-verify the facts: if the
    # editor somehow altered a name/score/minute, fall back to the unpolished
    # (already fact-checked) narration.
    on_step("polish", "Reviewing narration so it sounds natural")
    from .text_polish import polish
    polished = polish(narration, language=cfg.LANGUAGE, provider=cfg.LLM_PROVIDER)
    if polished != narration:
        check = verify(match, polished, cfg.LANGUAGE,
                       judge_provider=cfg.LLM_PROVIDER, use_judge=False)
        if check["passed"]:
            narration = polished
            result["narration"] = narration
        else:
            on_step("polish", "Edit changed a fact — keeping original wording")
    if check_cancel():
        return {**result, "status": "cancelled"}

    # --- 2. YouTube metadata -----------------------------------------
    on_step("metadata", "Generating YouTube metadata")
    meta = youtube_metadata(match, language=cfg.LANGUAGE, provider=cfg.LLM_PROVIDER)
    result["metadata"] = meta

    # --- 3. Media + voice + video (Phase 2) --------------------------
    video_path = None
    if do_video:
        try:
            on_step("media", "Collecting visuals (stock / graphics / flux)")
            from .media_provider import build_visuals
            images = build_visuals(cfg, match, fmt=fmt, on_step=on_step)

            on_step("voice", "Synthesising narration voice + subtitles")
            from .voice_generator import synthesize
            audio_path, subtitles = synthesize(cfg, narration)

            on_step("video", "Assembling .mp4")
            from .video_assembler import assemble
            video_path = assemble(cfg, match, images, audio_path, subtitles, meta, fmt=fmt)
            result["video"] = str(video_path)
        except ImportError:
            on_step("video", "Video modules not available yet (Phase 2) — skipping")

    # --- 3b. Social/blog text (multi-platform) -----------------------
    if do_social:
        on_step("social", "Generating blog/X/Instagram/LinkedIn text")
        from .content_generator import generate_all
        result["social"] = generate_all(cfg, match, provider=cfg.LLM_PROVIDER)

    # --- 4. Upload to YouTube (Phase 2) ------------------------------
    # Upload when explicitly requested OR when the profile has AUTO_UPLOAD on,
    # so generated summaries publish themselves with the configured privacy.
    if (do_upload or cfg.AUTO_UPLOAD) and video_path:
        on_step("upload", f"Uploading to YouTube ({cfg.YOUTUBE_PRIVACY})")
        try:
            from .publishers import upload_youtube
            result["youtube_url"] = upload_youtube(cfg, video_path, meta)
            result["youtube_privacy"] = cfg.YOUTUBE_PRIVACY
        except Exception as e:  # noqa: BLE001
            # A failed auto-upload must NOT lose the generated video. Record the
            # error and continue; it stays in the library to upload manually.
            on_step("upload", f"Auto-upload failed: {e}")
            result["upload_error"] = str(e)

    # --- 5. Persist content record -----------------------------------
    record = {**result, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    out = cfg.CONTENT_DIR / f"match_{match.fixture_id}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    result["status"] = "done"
    result["record_path"] = str(out)
    on_step("done", f"Finished {match.scoreline}")
    return result


def run_fixture_id(profile_id: str, fixture_id, **kwargs) -> dict:
    """Convenience: fetch a fixture by id from the configured source and run it."""
    from .data_sources import get_data_source
    cfg = BrandProfile(profile_id)
    match = get_data_source(cfg).fixture(fixture_id)
    return run_match(profile_id, match, **kwargs)
