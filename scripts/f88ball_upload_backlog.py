"""Publish every generated-but-unpublished video, oldest first, and keep going.

Why this exists rather than a loop around upload_content():

  ORDER. A channel that publishes a Monday recap before the Friday match it
  recaps reads as broken. Content ids sort lexically, not chronologically, so
  the order is taken from each record's own match date, with a round's digest
  placed after the matches it summarises.

  QUOTA. The YouTube Data API charges ~1600 units for one upload against a
  default allowance of 10000 a day, so roughly SIX uploads fit in a day. A
  sixteen-video backlog therefore cannot go out in one run no matter how it is
  written. Hitting the ceiling is treated as "come back tomorrow", not as a
  failure: the run stops cleanly, having already recorded every success, and the
  next run picks up exactly where it left off.

  RESUMABILITY. Nothing is tracked in memory. A video counts as published when
  its record carries a youtube_url, so a kill, a reboot or a quota wall all
  resume correctly, and no video is ever uploaded twice.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from core.brand_config import BrandProfile          # noqa: E402
from pipeline.upload_manager import pending_uploads, upload_content  # noqa: E402

# Gap between uploads. Not a quota measure — the quota is a daily budget, not a
# rate — but YouTube treats a burst of identical-looking uploads from one channel
# as a spam signal, and a channel that has never published before is exactly the
# kind that gets flagged.
_GAP_SECONDS = 90


def _match_dates(cfg: BrandProfile, content_ids: list[str]) -> dict:
    """Kick-off date for each match id, read from the data source.

    A match record stores the narration and the metadata but NOT the date it was
    played, and the file's own timestamp is worthless here: it records when the
    video was last RENDERED, so re-rendering the back catalogue for a new music
    track would re-date every match to today and publish a 15 August game after a
    23 August one. The fixture is the only honest source, so ask it.
    """
    out = {}
    try:
        from pipeline.data_sources import get_data_source
        source = get_data_source(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"[upload] cannot reach the data source for ordering ({e})")
        return out
    for cid in content_ids:
        if not cid.startswith("match_"):
            continue
        fid = cid.removeprefix("match_")
        try:
            m = source.fixture(fid)
            if getattr(m, "date", None):
                out[cid] = m.date
        except Exception:  # noqa: BLE001
            pass          # falls back below rather than aborting the whole run
    return out


def _round_end(cfg: BrandProfile, day: str) -> str:
    """Last calendar day of the round that opens on `day`."""
    if not day:
        return ""
    try:
        from core import competitions
        from pipeline.data_sources import get_data_source
        from pipeline.digest import matchday_days
        days = matchday_days(get_data_source(cfg), day,
                             competitions.digest_mode(cfg.COMPETITION))
        return max(days) if days else day
    except Exception:  # noqa: BLE001
        return day      # a single-day round is the safe assumption


def _sort_key(cfg: BrandProfile, content_id: str, dates: dict):
    """Chronological position of one item: (date, is_digest, id).

    A digest sorts to the END of its own round via the is_digest flag, so the
    round's matches publish first and the recap lands last, which is the order a
    viewer would expect to find them in.
    """
    rec_path = cfg.CONTENT_DIR / f"{content_id}.json"
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ("9999-99-99", 1, content_id)
    if rec.get("type") == "digest":
        # Sort a round recap by the round's LAST day, not its first. The record
        # is keyed by the opening day so that every day of a jornada maps to one
        # file, but publishing on that key would put the recap ahead of the
        # Saturday and Sunday games it summarises — a recap that appears before
        # the matches reads as broken.
        return (_round_end(cfg, rec.get("day", "")) or "9999-99-99", 1, content_id)
    day = dates.get(content_id) or rec.get("date") or ""
    if not day:
        # Last resort only. Flagged rather than silent, because ordering by
        # render time is exactly the bug this function exists to avoid.
        print(f"[upload] no match date for {content_id}; ordering it by file time")
        day = time.strftime("%Y-%m-%d", time.localtime(rec_path.stat().st_mtime))
    return (day, 0, content_id)


def _is_quota_error(exc: Exception) -> bool:
    """True when YouTube refused because the daily allowance is spent."""
    text = f"{exc}".lower()
    return ("quota" in text or "uploadlimitexceeded" in text
            or "ratelimitexceeded" in text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="laliga_es")
    ap.add_argument("--privacy", default="public",
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many uploads (0 = until quota runs out)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the publishing order and exit, uploading nothing")
    args = ap.parse_args()

    cfg = BrandProfile(args.profile)
    # The privacy the CALLER asked for wins. PRACTICE_MODE would otherwise force
    # every upload private, which would silently ignore an explicit --privacy.
    cfg.PRACTICE_MODE = False
    cfg.YOUTUBE_PRIVACY = args.privacy

    pending = pending_uploads(cfg)
    dates = _match_dates(cfg, pending)
    todo = sorted(pending, key=lambda c: _sort_key(cfg, c, dates))
    if not todo:
        print("[upload] nothing pending — every generated video is already published")
        return 0

    print(f"[upload] {len(todo)} pending, publishing as '{args.privacy}', oldest first:")
    for i, cid in enumerate(todo, 1):
        print(f"   {i:2}. {cid}   {_sort_key(cfg, cid, dates)[0]}")
    if args.dry_run:
        return 0

    done = 0
    for i, cid in enumerate(todo, 1):
        if args.limit and done >= args.limit:
            print(f"[upload] reached --limit {args.limit}; {len(todo) - done} still pending")
            break
        try:
            print(f"[upload] {i}/{len(todo)} {cid} ...", flush=True)
            res = upload_content(cfg, cid)
            done += 1
            print(f"[upload] OK {cid} -> {res['youtube_url']} ({res['privacy']})", flush=True)
        except Exception as e:  # noqa: BLE001
            if _is_quota_error(e):
                print(f"[upload] daily quota reached after {done} upload(s). "
                      f"{len(todo) - done} still pending — they go out on the next run.")
                return 0          # not a failure: the backlog simply spans days
            print(f"[upload] FAILED {cid}: {e}", flush=True)
            continue              # a bad item must not block the rest of the queue
        if i < len(todo):
            time.sleep(_GAP_SECONDS)

    print(f"[upload] finished: {done} uploaded, "
          f"{len(pending_uploads(cfg))} still pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
