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
import fcntl
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from core.brand_config import BrandProfile  # noqa: E402
from pipeline.upload_manager import (  # noqa: E402
    blocked_uploads,
    pending_uploads,
    revalidate_held,
    upload_content,
)

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


_ROUND_END_CACHE: dict = {}


def _round_end(cfg: BrandProfile, day: str, competition: str = "") -> str:
    """Last calendar day of the round that opens on `day`.

    Memoised because it is not cheap and it is asked repeatedly: sorting calls
    the key function per element and the listing prints it again, and each miss
    fans out to a week of fixture lookups across ESPN AND the roninfc.fans
    supporters site — which is a small community server the data source politely
    rate-limits, not an API to hammer once per sort comparison.
    """
    if not day:
        return ""
    ck = (day, competition)
    if ck in _ROUND_END_CACHE:
        return _ROUND_END_CACHE[ck]
    try:
        from core import competitions
        from pipeline.data_sources import get_data_source
        from pipeline.digest import matchday_days

        # Scope the round to the recap's OWN competition. On a feed carrying
        # several of them the week has no empty day, so an unscoped walk would
        # stretch every round to the look-back limit and sort every recap to the
        # same late date — losing the ordering this function exists to produce.
        ident = competition or cfg.COMPETITION
        keep = None
        if competition:
            keep = lambda m: competitions.key_for(m.competition) == competition  # noqa: E731
        days = matchday_days(get_data_source(cfg), day,
                             competitions.digest_mode(ident), keep)
        end = max(days) if days else day
    except Exception:  # noqa: BLE001
        end = day       # a single-day round is the safe assumption
    _ROUND_END_CACHE[ck] = end
    return end


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
        return (_round_end(cfg, rec.get("day", ""), rec.get("competition", ""))
                or "9999-99-99", 1, content_id)
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


def _notify(title: str, message: str) -> None:
    """Best-effort macOS notification. Never lets the uploader fail over UI.

    The log alone was not enough: this job writes a line a minute forever, so a
    hold recorded there is indistinguishable from the noise around it. A held
    video is a decision waiting on a human, and it needs to reach one.
    """
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification {json.dumps(message)} with title {json.dumps(title)}'],
            check=False, capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001 — a missing/renamed osascript is not fatal
        pass


def _report_held(cfg: BrandProfile, blocked: list, announce: bool) -> None:
    """Print what a gate is holding, in full the FIRST time each item appears.

    Printing the full block on every pass would bury it: at a pass a minute,
    four held videos is fourteen thousand lines a day and the log becomes the
    same wall of noise that hid the problem. So the detail (and the
    notification) fire when the held SET changes, and every other pass gets one
    line — enough to see the hold is still there while scrolling.
    """
    seen_path = cfg.OUTPUT_DIR / ".held_reported.json"
    try:
        seen = set(json.loads(seen_path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        seen = set()
    current = {cid for cid, _ in blocked}
    fresh = current - seen

    if not current:
        # Everything held has since been released. Forget them, or the state
        # file keeps ids that can never come back — a released video carries a
        # youtube_url and is excluded from the unpublished set for good — and
        # the record of what has already been announced drifts from reality.
        if seen and announce:
            try:
                seen_path.unlink()
            except OSError:
                pass
        return

    if fresh or not announce:
        print(f"[upload] {len(blocked)} rendered video(s) HELD BACK by a gate — "
              f"not published, awaiting review:")
        for cid, reasons in blocked:
            print(f"   {'!' if cid in fresh else ' '} {cid}")
            for reason in reasons:
                print(f"       {reason}")
        print("[upload] review, then publish with: uv run python "
              "scripts/f88ball_upload_backlog.py --publish-held <id>")
    else:
        print(f"[upload] {len(blocked)} video(s) still held back "
              f"({', '.join(sorted(current))}) — awaiting review")

    if fresh and announce:
        _notify("F88tball — video sin publicar",
                f"{len(fresh)} vídeo(s) retenidos por el guardrail: "
                f"{', '.join(sorted(fresh))}")
    if announce and current != seen:
        try:
            seen_path.write_text(json.dumps(sorted(current)), encoding="utf-8")
        except OSError:
            pass          # losing the state only costs a repeated report


def _acquire_lock(cfg: BrandProfile):
    """Take an exclusive per-profile lock, or return None if a run is already up.

    A pass over a full backlog takes about a quarter of an hour, so two runs
    started minutes apart would overlap for almost all of it. Both would read the
    same pending list before either finished a transfer, and both would publish —
    two public copies of the same match, with the second overwriting the first's
    URL so nothing is left pointing at the orphan. launchd will not start a
    second copy of the same job, but that is not the only way a run starts: a
    manual kickstart, the API's own upload worker, or someone running the script
    by hand all bypass it. The lock is held by the process and released by the
    kernel on exit, so a crash cannot leave it stuck.
    """
    lock_path = cfg.OUTPUT_DIR / ".upload.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "w")          # noqa: SIM115 — must outlive this call
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="laliga_es")
    ap.add_argument("--privacy", default="public",
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many uploads (0 = until quota runs out)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the publishing order and exit, uploading nothing")
    ap.add_argument("--publish-held", nargs="+", metavar="ID", default=None,
                    help="publish these held-back ids after a human reviewed "
                         "them (bypasses the guardrail gate for those ids ONLY)")
    args = ap.parse_args()

    cfg = BrandProfile(args.profile)
    lock = None
    if not args.dry_run:                   # a dry run publishes nothing
        lock = _acquire_lock(cfg)
        if lock is None:
            print("[upload] another upload run is already in progress — leaving it to finish")
            return 0
    # The privacy the CALLER asked for wins. PRACTICE_MODE would otherwise force
    # every upload private, which would silently ignore an explicit --privacy.
    cfg.PRACTICE_MODE = False
    cfg.YOUTUBE_PRIVACY = args.privacy

    # An explicit, human-reviewed override. Deliberately a SEPARATE mode rather
    # than a flag that relaxes the gate for everything: the guardrail's decision
    # stands for the queue, and releasing a video is a per-id act that names the
    # id out loud. It still refuses to touch anything the gate is not holding,
    # so a typo cannot quietly publish an unrelated match.
    if args.publish_held:
        held = dict(blocked_uploads(cfg))
        done = 0
        for cid in args.publish_held:
            if cid not in held:
                print(f"[upload] {cid} is not held back — nothing to release")
                continue
            print(f"[upload] releasing {cid} (was held: {'; '.join(held[cid])})",
                  flush=True)
            try:
                res = upload_content(cfg, cid)
                done += 1
                print(f"[upload] OK {cid} -> {res['youtube_url']} ({res['privacy']})",
                      flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[upload] FAILED {cid}: {e}", flush=True)
                continue
            if cid != args.publish_held[-1]:
                time.sleep(_GAP_SECONDS)
        print(f"[upload] released {done} held video(s)")
        return 0

    # Re-check the held set against TODAY's guardrail and today's match data
    # before deciding anything. A verdict is written once and read forever, so
    # without this a video refused by a check that has since been fixed stays
    # refused for good — which is how a correct Racing 2-1 Alaves recap sat
    # rendered on disk while the fix for the check that refused it was already
    # in the tree. Cheap: it walks the handful of records a gate is holding.
    for cid, before, after in revalidate_held(cfg):
        if after:
            print(f"[upload] re-checked {cid} — still held: {'; '.join(after)}")
        else:
            print(f"[upload] re-checked {cid} — the hold no longer applies "
                  f"(was: {'; '.join(before)}); queued for publishing")

    pending = pending_uploads(cfg)
    # Report what a gate is holding back BEFORE deciding there is nothing to do.
    # A held video is finished, sitting on disk, and invisible: the run used to
    # print "every generated video is already published" while four rendered
    # matches waited behind a guardrail, so the only signal that anything was
    # wrong was a viewer noticing a match had never appeared on the channel.
    # Called even when nothing is held, so the "already announced" state is
    # cleared once the last hold is released. A dry run is a human asking on
    # purpose: it always shows the full detail, and never consumes that state.
    blocked = blocked_uploads(cfg)
    _report_held(cfg, blocked, announce=not args.dry_run)

    dates = _match_dates(cfg, pending)
    todo = sorted(pending, key=lambda c: _sort_key(cfg, c, dates))
    if not todo:
        print("[upload] nothing pending"
              + (f" — {len(blocked)} held back (above)" if blocked
                 else " — every generated video is already published"))
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
