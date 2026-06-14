"""
cache.py — lightweight on-disk cache for football API responses.

API-Football's free plan allows only 100 requests/day. Finished matches and
their scorers never change, so caching them avoids burning the quota on repeated
dashboard loads. Cache entries are JSON files under .cache/ keyed by a stable
hash of the request.
"""

import hashlib
import json
import time
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "matches"
_TTL_SECONDS = 60 * 60 * 6     # 6h: finished matches are stable; refresh occasionally


def _key(parts: tuple) -> Path:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{h}.json"


def get(parts: tuple, max_age: float | None = None):
    """Return cached value for `parts`, or None if missing/expired.

    `max_age` overrides the default TTL. The 6h default exists to protect
    API-Football's 100-requests/day quota on data that no longer changes;
    a LIVE scoreboard poll must pass a short max_age instead, or a snapshot
    taken mid-match keeps answering "in progress" for hours after full time."""
    f = _key(parts)
    if not f.exists():
        return None
    try:
        blob = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    ttl = _TTL_SECONDS if max_age is None else max_age
    if time.time() - blob.get("_ts", 0) > ttl:
        return None
    return blob.get("data")


def get_stale(parts: tuple):
    """Return cached value ignoring expiry (used when the API quota is gone)."""
    f = _key(parts)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("data")
    except json.JSONDecodeError:
        return None


def put(parts: tuple, data) -> None:
    """Store `data` for `parts`."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = _key(parts)
    f.write_text(json.dumps({"_ts": time.time(), "data": data},
                            ensure_ascii=False), encoding="utf-8")
