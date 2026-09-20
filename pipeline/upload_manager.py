"""
upload_manager.py — YouTube upload helpers shared by the manual, automatic,
scheduled and bulk paths.

  • upload_content(cfg, content_id)  upload ANY generated item (match_* or
    digest_*) by its content id (the JSON/.mp4 stem), writing the resulting
    watch URL back into its content record.
  • a tiny JSON-backed SCHEDULE queue (queue/list/cancel) so videos can be set
    to upload at a chosen time, drained by a background worker in the API.

Privacy is the profile's YOUTUBE_PRIVACY (forced to private in PRACTICE_MODE),
configurable from .env — nothing is published unintentionally.
"""

import json
import time
from pathlib import Path

from core.brand_config import BrandProfile


def _record_path(cfg: BrandProfile, content_id: str) -> Path:
    return cfg.CONTENT_DIR / f"{content_id}.json"


def _video_path(cfg: BrandProfile, content_id: str) -> Path:
    return cfg.VIDEO_DIR / f"{content_id}.mp4"


def _valid_id(content_id: str) -> bool:
    return (content_id.startswith(("match_", "digest_"))
            and "/" not in content_id and ".." not in content_id)


def upload_content(cfg: BrandProfile, content_id: str) -> dict:
    """Upload one generated item to YouTube by its content id and persist the URL.

    Works for both per-match (match_<id>) and daily-digest (digest_<day>_<fmt>)
    records. Returns {ok, youtube_url, privacy}. Raises on bad id / missing file.
    """
    if not _valid_id(content_id):
        raise ValueError("Invalid content id")
    vid = _video_path(cfg, content_id)
    if not vid.exists():
        raise FileNotFoundError("Generate the video first")

    rec_path = _record_path(cfg, content_id)
    record = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {}
    # Re-read the record HERE, immediately before uploading, and stop if it is
    # already published. Callers decide what to upload from a list built before
    # the first transfer began, and a pass over a full backlog takes a quarter of
    # an hour — long enough for another run, the API's upload worker or a manual
    # kick to have published this very item in the meantime. Uploading again
    # would put a second public copy on the channel and overwrite the first
    # one's URL below, orphaning it where nothing can find it to clean up.
    if record.get("youtube_url"):
        return {"ok": True, "youtube_url": record["youtube_url"],
                "privacy": record.get("youtube_privacy", cfg.YOUTUBE_PRIVACY),
                "already_published": True}
    # The uploader appends the hashtags to the description itself, so the
    # fallback description here must be real text, never the tags again.
    scorelines = "\n".join(m.get("scoreline", "") for m in record.get("matches", []))
    meta = record.get("metadata") or {
        "title": record.get("scoreline") or (f"Resumen del día · {record.get('day')}"
                                             if record.get("day") else "Resumen"),
        "description": (record.get("scoreline") or scorelines or "Resumen"),
        "tags": record.get("tags", []),
    }

    from pipeline.publishers import upload_youtube
    url = upload_youtube(cfg, vid, meta)
    privacy = "private" if cfg.PRACTICE_MODE else cfg.YOUTUBE_PRIVACY

    record["youtube_url"] = url
    record["youtube_privacy"] = privacy
    if rec_path.exists() or record:
        rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    # Free the local artifacts now that the upload is confirmed, exactly as the
    # inline path in runner.py and digest.py does. This function is the DEFERRED
    # path — the backlog uploader and the API's worker both come through here —
    # and it used to skip the cleanup entirely, so anything published a pass
    # later stayed on disk forever. That was invisible while nearly everything
    # uploaded inline the moment it was generated; a channel whose daily output
    # regularly exceeds the YouTube quota publishes most of its videos this way.
    #
    # cleanup_local_artifacts re-checks the url itself and deletes nothing
    # unless it is a confirmed watch URL, so a failed upload keeps its only copy.
    # The record JSON is never touched: it holds the url and is what stops the
    # item being published twice.
    from pipeline.publishers import cleanup_local_artifacts
    # The .mp4 and this item's own crowd images. Deliberately NOT the match
    # narration audio: single-match runs all write the same scratch
    # "narration.mp3", so deleting it here — long after generation, from a
    # different process — could pull the audio out from under a match being
    # rendered right now. runner.py cleans it inline, where it is still ours.
    artifacts = [vid, cfg.IMAGE_DIR / content_id]
    if record.get("type") == "digest":
        # A digest's heavy pieces are per-SEGMENT and named after each match, not
        # after the digest itself.
        for m in record.get("matches") or []:
            fid = m.get("fixture_id")
            if fid is None:
                continue
            artifacts.append(cfg.OUTPUT_DIR / f"seg_{fid}.mp3")
            artifacts.append(cfg.IMAGE_DIR / f"match_{fid}")
    cleanup_local_artifacts(url, artifacts)
    return {"ok": True, "youtube_url": url, "privacy": privacy}


def hold_reasons(record: dict) -> list[str]:
    """Why a rendered video is not eligible for automatic publishing.

    An empty list means nothing is holding it back. Returning the REASONS
    rather than a bool is the whole point: a gate that only says "no" is
    indistinguishable from having nothing to do, which is exactly how four
    finished matches — one of them a 0-5 Barcelona win at Mestalla — sat on
    disk for days while the uploader reported "every generated video is
    already published" once a minute.
    """
    reasons = []
    if record.get("upload_skipped"):
        reasons.append("held back at generation (upload_skipped)")
    guard = record.get("guardrail") or {}
    if guard and not guard.get("passed", True):
        issues = (guard.get("facts") or {}).get("issues") or []
        judge = guard.get("judge") or {}
        ungrounded = bool(judge) and not judge.get("grounded", True)
        if issues:
            reasons.append("facts — " + "; ".join(issues))
        if ungrounded:
            reasons.append("judge — " + (judge.get("reason") or "not grounded"))
        if not issues and not ungrounded:
            reasons.append("narration guardrail did not pass")
    meta_guard = record.get("metadata_guardrail") or {}
    if meta_guard and not meta_guard.get("ok", True):
        issues = meta_guard.get("issues") or []
        reasons.append("metadata — " + ("; ".join(issues) if issues
                                        else "guardrail did not pass"))
    return reasons


def _unpublished(cfg: BrandProfile):
    """(content_id, record) for every rendered video with no YouTube URL yet."""
    for f in sorted(cfg.CONTENT_DIR.glob("*.json")):
        if not _valid_id(f.stem) or not _video_path(cfg, f.stem).exists():
            continue
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if rec.get("youtube_url"):
            continue
        yield f.stem, rec


def pending_uploads(cfg: BrandProfile) -> list[str]:
    """Content ids that have a video, are NOT on YouTube, and no gate holds back.

    Never queue what a gate deliberately held back: publishing exactly the
    records the guardrail refused would quietly undo the decision that kept
    them back. What the gate holds is reported by blocked_uploads().
    """
    return [cid for cid, rec in _unpublished(cfg) if not hold_reasons(rec)]


def blocked_uploads(cfg: BrandProfile) -> list[tuple[str, list[str]]]:
    """(content_id, reasons) for rendered videos a gate is holding back.

    These are NOT failures to retry — a human decides whether the narration is
    wrong or the guardrail is over-eager, then either fixes the record or
    publishes it deliberately. They must simply never be silent again.
    """
    return [(cid, reasons) for cid, rec in _unpublished(cfg)
            if (reasons := hold_reasons(rec))]


def revalidate(cfg: BrandProfile, content_id: str, record: dict) -> dict | None:
    """Re-run the DETERMINISTIC gates against today's code and today's data.

    A verdict is a SNAPSHOT, and the gate reads it forever. Whatever the
    guardrail believed at the moment of generation is frozen into the record,
    so a video held by a check that was later fixed stays held for good — the
    guardrail improves, and the video it wrongly refused never learns about it.
    Three real videos were stuck exactly there: a Racing 2-1 Alaves recap whose
    score check could not read "Racing de Santander 2, Alaves 1", a Dortmund tie
    whose narration DOES call the penalty a penalty, and a Getafe description
    that correctly says "amarillos" and "de derecho" while its frozen verdict
    insists it says red and the wrong foot.

    Only the deterministic layer is re-run, and only in the direction of the
    facts:

      · The LLM judge's verdict is left exactly as it was. Re-running it costs a
        call and could flip on model drift alone, so 'not grounded' stands until
        a human moves it — an opinion is not something to re-roll until it
        agrees.
      · upload_skipped is never touched. That is a decision taken at generation
        time, not a check with a right answer.
      · If the fixture cannot be fetched, NOTHING changes and the hold stands.
        Failing closed is the only safe direction here: releasing a video
        because the data that would contradict it is missing is precisely how a
        wrong match reaches the channel.

    Returns the updated record, or None when nothing changed.
    """
    if not content_id.startswith("match_") or record.get("upload_skipped"):
        return None                 # a digest carries many matches, not one
    narration = record.get("narration") or ""
    if not narration:
        return None
    try:
        from pipeline.data_sources import get_data_source
        match = get_data_source(cfg).fixture(content_id.removeprefix("match_"))
    except Exception:               # noqa: BLE001 — unreachable source, keep holding
        return None
    if match is None or match.home_goals is None or match.away_goals is None:
        return None

    import copy

    from agents.guardrail import facts_check

    updated = copy.deepcopy(record)
    guard = updated.setdefault("guardrail", {})
    guard["facts"] = facts_check(match, narration, cfg.LANGUAGE)
    # The judge keeps its say: a narration it called ungrounded stays held even
    # when every deterministic check now passes.
    guard["passed"] = (guard["facts"]["ok"]
                       and (guard.get("judge") or {}).get("grounded", True))

    meta = updated.get("metadata") or {}
    if meta.get("title") or meta.get("description"):
        # ordered_score=False: a title carries the final FIRST and the
        # description may recount a running score last, so the narration's
        # "last token is the final" rule would false-fail here.
        updated["metadata_guardrail"] = facts_check(
            match, f"{meta.get('title', '')}\n{meta.get('description', '')}",
            cfg.LANGUAGE, ordered_score=False)

    updated["revalidated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return updated if hold_reasons(updated) != hold_reasons(record) else None


def revalidate_held(cfg: BrandProfile) -> list[tuple[str, list[str], list[str]]]:
    """Re-check everything a gate is holding, and persist any verdict that moved.

    Runs over the HELD set only — a handful of records — so the cost is a few
    cached fixture lookups, not a pass over the whole back catalogue.

    Returns (content_id, reasons_before, reasons_after) for each record whose
    verdict changed; an empty `reasons_after` means the video is now free to be
    published on the next pass.
    """
    moved = []
    for cid, reasons in blocked_uploads(cfg):
        updated = revalidate(cfg, cid, json.loads(
            _record_path(cfg, cid).read_text(encoding="utf-8")))
        if updated is None:
            continue
        _record_path(cfg, cid).write_text(
            json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
        moved.append((cid, reasons, hold_reasons(updated)))
    return moved


# ── Scheduled-upload queue (JSON-backed, one file per profile) ───────
def _queue_path(cfg: BrandProfile) -> Path:
    return cfg.OUTPUT_DIR / "upload_queue.json"


def _read_queue(cfg: BrandProfile) -> list[dict]:
    p = _queue_path(cfg)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _write_queue(cfg: BrandProfile, items: list[dict]) -> None:
    _queue_path(cfg).write_text(json.dumps(items, indent=2, ensure_ascii=False),
                               encoding="utf-8")


def schedule_upload(cfg: BrandProfile, content_id: str, when_epoch: float) -> dict:
    """Queue `content_id` to upload at `when_epoch` (unix seconds). Replaces any
    existing pending entry for the same id."""
    if not _valid_id(content_id):
        raise ValueError("Invalid content id")
    if not _video_path(cfg, content_id).exists():
        raise FileNotFoundError("Generate the video first")
    items = [i for i in _read_queue(cfg)
             if not (i["content_id"] == content_id and i["status"] == "pending")]
    items.append({"content_id": content_id, "when": float(when_epoch),
                  "status": "pending", "queued_at": time.time()})
    _write_queue(cfg, items)
    return {"ok": True, "content_id": content_id, "when": float(when_epoch)}


def list_schedule(cfg: BrandProfile) -> list[dict]:
    return _read_queue(cfg)


def cancel_scheduled(cfg: BrandProfile, content_id: str) -> dict:
    items = [i for i in _read_queue(cfg)
             if not (i["content_id"] == content_id and i["status"] == "pending")]
    _write_queue(cfg, items)
    return {"ok": True}


def drain_due(cfg: BrandProfile, now: float | None = None) -> list[dict]:
    """Upload every PENDING entry whose time has come. Marks each done/failed and
    returns what was processed. Called by the API's background worker."""
    now = time.time() if now is None else now
    items = _read_queue(cfg)
    processed = []
    changed = False
    for it in items:
        if it.get("status") != "pending" or it.get("when", 0) > now:
            continue
        changed = True
        try:
            res = upload_content(cfg, it["content_id"])
            it["status"] = "done"
            it["youtube_url"] = res["youtube_url"]
        except Exception as e:  # noqa: BLE001
            it["status"] = "failed"
            it["error"] = str(e)
        it["processed_at"] = now
        processed.append(it)
    if changed:
        _write_queue(cfg, items)
    return processed
