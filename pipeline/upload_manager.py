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
    return {"ok": True, "youtube_url": url, "privacy": privacy}


def pending_uploads(cfg: BrandProfile) -> list[str]:
    """Content ids that have a video but are NOT yet on YouTube."""
    out = []
    for f in sorted(cfg.CONTENT_DIR.glob("*.json")):
        if not _valid_id(f.stem) or not _video_path(cfg, f.stem).exists():
            continue
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not rec.get("youtube_url"):
            out.append(f.stem)
    return out


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
