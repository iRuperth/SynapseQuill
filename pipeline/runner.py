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
    # Regenerate until it passes (up to 3 attempts total), feeding the failed
    # checks back into the prompt: a rejected narration must never reach the
    # voice/video — a wrong card colour and a misspelled scorer both shipped
    # before this loop existed.
    on_step("guardrail", "Verifying narration is grounded in match facts")
    from agents.guardrail import verify
    verdict = verify(match, narration, cfg.LANGUAGE, judge_provider=cfg.JUDGE_PROVIDER)
    result["guardrail"] = verdict
    for attempt in range(2):
        if verdict["passed"]:
            break
        reasons = "; ".join(verdict["facts"]["issues"]) or \
            verdict.get("judge", {}).get("reason", "")
        on_step("guardrail", f"Narration failed checks ({reasons}) — regenerating "
                             f"({attempt + 2}/3)")
        narration = narrate(match, language=cfg.LANGUAGE,
                            system_preamble=cfg.system_preamble +
                            "\nBe strictly factual. A previous draft was rejected "
                            f"for: {reasons}. Copy every player name and card "
                            "colour EXACTLY as given in the facts.",
                            provider=cfg.LLM_PROVIDER)
        verdict = verify(match, narration, cfg.LANGUAGE, judge_provider=cfg.JUDGE_PROVIDER)
        result["narration"] = narration
        result["guardrail"] = verdict
    if not verdict["passed"]:
        on_step("guardrail", "WARNING: narration still failing after 3 attempts — "
                             "shipping the last draft; review before publishing")

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
                       judge_provider=cfg.JUDGE_PROVIDER, use_judge=False)
        if check["passed"]:
            narration = polished
            result["narration"] = narration
        else:
            on_step("polish", "Edit changed a fact — keeping original wording")
    if check_cancel():
        return {**result, "status": "cancelled"}

    # --- 2. YouTube metadata -----------------------------------------
    # The title/description is LLM text too — verify it against the facts just
    # like the narration (a right-footed goal once shipped as 'disparo de
    # zurda' in the description). Deterministic layer only: cheap, no judge.
    on_step("metadata", "Generating YouTube metadata")
    from agents.guardrail import facts_check
    meta = youtube_metadata(match, language=cfg.LANGUAGE, provider=cfg.LLM_PROVIDER)
    # Verify-then-regenerate: check at the TOP of the loop so EVERY draft —
    # including the last — is verified (the old loop shipped the 3rd draft
    # unchecked). ordered_score=False: the title carries the final first and
    # the description may recount a running score last, so the play-by-play
    # 'last token is the final' rule does not apply here.
    for attempt in range(3):
        meta_check = facts_check(match, f"{meta['title']}\n{meta['description']}",
                                 cfg.LANGUAGE, ordered_score=False)
        if meta_check["ok"] or attempt == 2:
            break
        reasons = "; ".join(meta_check["issues"])
        on_step("metadata", f"Description failed fact checks ({reasons}) — "
                            f"regenerating ({attempt + 2}/3)")
        meta = youtube_metadata(match, language=cfg.LANGUAGE,
                                provider=cfg.LLM_PROVIDER, feedback=reasons)
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
    # GATE: never AUTO-publish a narration that failed every guardrail attempt
    # (it may contain a hallucination the retries could not fix). The video is
    # still generated and saved — it just waits for a manual upload/review.
    # An explicit do_upload (a human ran this on purpose) is honoured anyway.
    guardrail_failed = not result.get("guardrail", {}).get("passed", True)
    block_auto = cfg.AUTO_UPLOAD and not do_upload and guardrail_failed
    if block_auto:
        on_step("upload", "Skipped auto-upload: narration failed the guardrail "
                          "— left in the library for manual review")
        result["upload_skipped"] = "guardrail failed"
    elif (do_upload or cfg.AUTO_UPLOAD) and video_path:
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


def _topic_slug(topic: str) -> str:
    """A short, filesystem-safe slug from a topic, for the output stem."""
    base = "".join(c if c.isalnum() else "-" for c in (topic or "").lower())
    base = "-".join(p for p in base.split("-") if p)[:48]
    return base or "tema"


def run_topic_video(profile_id: str, topic: str, *,
                    source_text: str = "", audience: str = "",
                    on_step: StepCb = _noop_step,
                    check_cancel: CancelCb = _noop_cancel,
                    do_video: bool = True,
                    do_upload: bool = False,
                    video_format: str = "reel") -> dict:
    """Generate a topic/educational video (no match): clean celebration backdrop
    + logo, narration and subtitles.

    `topic` is the subject ("nuevas reglas del Mundial"). If `source_text` is
    given, the narration is grounded ONLY in that text; otherwise the model
    explains the topic without fabricating facts. Returns a result dict.
    """
    from .video_format import get_format
    cfg = BrandProfile(profile_id)
    fmt = get_format(video_format)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = f"topic_{_topic_slug(topic)}_{stamp}"
    result: dict = {"type": "topic", "topic": topic, "format": fmt.key}

    # --- 1. Narration -------------------------------------------------
    on_step("narrate", f"Writing narration for «{topic}»")
    from .narrator import narrate_topic, topic_metadata
    narration = narrate_topic(
        topic, language=cfg.LANGUAGE, system_preamble=cfg.system_preamble,
        provider=cfg.LLM_PROVIDER, video_format=fmt.key,
        source_text=source_text, audience=audience)
    result["narration"] = narration
    if check_cancel():
        return {**result, "status": "cancelled"}

    # --- 1b. Polish: make the script sound human ----------------------
    # No match guardrail here (there is no match to verify against) — the
    # grounding is the user's own text or the no-fabrication rule. We still run
    # the deterministic Spanish polish so the spoken script reads naturally.
    on_step("polish", "Reviewing narration so it sounds natural")
    from .text_polish import polish
    narration = polish(narration, language=cfg.LANGUAGE, provider=cfg.LLM_PROVIDER)
    result["narration"] = narration

    # --- 2. YouTube metadata -----------------------------------------
    on_step("metadata", "Generating YouTube metadata")
    meta = topic_metadata(topic, narration, language=cfg.LANGUAGE,
                          provider=cfg.LLM_PROVIDER)
    result["metadata"] = meta
    if check_cancel():
        return {**result, "status": "cancelled"}

    # --- 3. Backdrop + voice + video ---------------------------------
    video_path = None
    if do_video:
        on_step("media", "Generating clean celebration backdrop")
        from .media_provider import build_topic_backdrop
        backdrop = build_topic_backdrop(cfg, _topic_slug(topic) + "_" + stamp,
                                        fmt=fmt, on_step=on_step)

        on_step("voice", "Synthesising narration voice + subtitles")
        from .voice_generator import synthesize
        audio_path, subtitles = synthesize(cfg, narration, name=stem)

        on_step("video", "Assembling .mp4")
        from .video_assembler import assemble_plain
        video_path = assemble_plain(cfg, stem, backdrop, audio_path, subtitles, fmt=fmt)
        result["video"] = str(video_path)

    # --- 4. Upload to YouTube (optional) -----------------------------
    if (do_upload or cfg.AUTO_UPLOAD) and video_path:
        on_step("upload", f"Uploading to YouTube ({cfg.YOUTUBE_PRIVACY})")
        try:
            from .publishers import upload_youtube
            result["youtube_url"] = upload_youtube(cfg, video_path, meta)
            result["youtube_privacy"] = cfg.YOUTUBE_PRIVACY
        except Exception as e:  # noqa: BLE001
            on_step("upload", f"Auto-upload failed: {e}")
            result["upload_error"] = str(e)

    # --- 5. Persist content record -----------------------------------
    record = {**result, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    out = cfg.CONTENT_DIR / f"{stem}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    result["status"] = "done"
    result["record_path"] = str(out)
    on_step("done", f"Finished «{topic}»")
    return result
