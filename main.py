"""
main.py — F88tball CLI entrypoint.

The profile picks the competition (laliga_es -> LaLiga, worldcup_es -> the
World Cup), so the same commands cover any of them.

Usage:
    # Generate a video for one finished match now
    python main.py --profile laliga_es --match 401882920

    # List the profile's fixtures (today's, or the latest finished)
    python main.py --profile laliga_es --fixtures

    # Run the auto-monitor: poll the data source and generate videos as
    # matches finish, plus the recap when a whole matchday wraps up
    python main.py --profile laliga_es --scheduler --interval 90

    # Print a short report of generated content
    python main.py --profile laliga_es --report
"""

import argparse
import json
import time

from dotenv import load_dotenv

load_dotenv()

from core.brand_config import BrandProfile, list_profiles  # noqa: E402
from core.tracing import setup_tracing  # noqa: E402
from pipeline.data_sources import get_data_source  # noqa: E402
from pipeline.runner import run_fixture_id, run_match  # noqa: E402


def cmd_fixtures(cfg: BrandProfile):
    source = get_data_source(cfg)
    matches = source.fixtures_on() if cfg.MATCH_MODE == "today" else source.latest_finished()
    for m in matches:
        print(f"  [{m.status:>14}] {m.fixture_id}  {m.scoreline}")


def cmd_match(cfg: BrandProfile, fixture_id: str, upload: bool, social: bool):
    result = run_fixture_id(cfg.id, fixture_id, do_video=True,
                           do_upload=upload, do_social=social)
    print(json.dumps({k: v for k, v in result.items() if k != "social"},
                     indent=2, ensure_ascii=False))


def cmd_report(cfg: BrandProfile):
    files = sorted(cfg.CONTENT_DIR.glob("match_*.json"))
    print(f"  {len(files)} generated item(s) for profile '{cfg.id}':")
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        print(f"   - {rec.get('scoreline')}  ({rec.get('generated_at')})")


# The matchday recap is always the long horizontal video.
_DIGEST_FORMAT = "youtube"


# How many past days to look back over for an unbuilt digest. The window lets a
# round that was missed while still in progress still get its recap a few days
# later. A league jornada can run Friday to Monday, so the look-back has to
# outreach a whole round or the Friday games would age out before Monday's
# kick-off closes the round.
_DIGEST_LOOKBACK_DAYS = 8


def _maybe_run_digest(cfg: BrandProfile, source, upload: bool):
    """Build the digest for every recent ROUND whose fixtures have all finished.

    What counts as a round comes from the competition preset: a World Cup day is
    its own recap, while a LaLiga jornada spans Friday to Monday and must be ONE
    recap. So each candidate day is first resolved to its round, and the round is
    keyed by its first day — every day of a jornada maps to the same record file,
    which is what stops a four-day round from producing four near-identical
    digests. Today is excluded so a round is only summarised once fully played,
    and the record file marks it done so it never re-generates."""
    from datetime import date, timedelta

    from core import competitions
    from pipeline.digest import matchday_days, run_daily_digest

    mode = competitions.digest_mode(cfg.COMPETITION)
    built: set[str] = set()
    # Oldest first, so missed rounds are filled in chronological order. Skip
    # today (offset 0): its games may still be in progress.
    for offset in range(_DIGEST_LOOKBACK_DAYS, 0, -1):
        d = date.today() - timedelta(days=offset)
        days = matchday_days(source, d.isoformat(), mode)
        anchor = days[0]
        if anchor in built:
            continue                            # same round, already handled
        built.add(anchor)
        if (cfg.CONTENT_DIR / f"digest_{anchor}_{_DIGEST_FORMAT}.json").exists():
            continue                            # already built
        # A round is only ready when EVERY day of it has games and all of them
        # have finished — including a Monday-night closer still in progress.
        fixtures = [m for day in days for m in source.fixtures_on(day)]
        if not fixtures or not all(m.is_finished for m in fixtures):
            continue                            # no games / still playing
        print(f"[scheduler] round {anchor} complete ({len(fixtures)} matches) "
              f"over {len(days)} day(s) — building the digest...")
        run_daily_digest(cfg.id, anchor, _DIGEST_FORMAT, upload=upload or None,
                         on_step=lambda step, msg: print(f"[digest:{step}] {msg}"))


def cmd_scheduler(cfg: BrandProfile, interval: int, upload: bool):
    """Poll the data source and generate a video as each match finishes. When a
    whole matchday wraps up, build (and upload) its digest recap too."""
    source = get_data_source(cfg)
    # Seed from the content records on disk so a restart (reboot, crash,
    # launchd relaunch) never regenerates and re-uploads a match it already
    # produced. Fixture ids may be int or str depending on the source, so
    # seed both forms.
    processed: set = set()
    for f in cfg.CONTENT_DIR.glob("match_*.json"):
        fid = f.stem.removeprefix("match_")
        processed.add(fid)
        if fid.isdigit():
            processed.add(int(fid))
    print(f"[scheduler] watching {source.name} fixtures every {interval}s "
          f"(profile '{cfg.id}'). Ctrl+C to stop.")
    while True:
        try:
            for match in source.poll_finished(processed):
                print(f"[scheduler] finished: {match.scoreline} — generating...")
                run_match(cfg.id, match, do_video=True, do_upload=upload)
            _maybe_run_digest(cfg, source, upload)
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] error: {e}")
        time.sleep(interval)


def main():
    p = argparse.ArgumentParser(description="F88tball — football highlight generator")
    p.add_argument("--profile", help="profile id under profiles/")
    # str, not int: a merged feed namespaces ids as "<leg>-<id>", e.g.
    # --match laliga-401882920. A plain numeric id still works.
    p.add_argument("--match", help="generate a video for this fixture id")
    p.add_argument("--fixtures", action="store_true", help="list today's fixtures")
    p.add_argument("--scheduler", action="store_true",
                   help="auto-generate as matches finish + the digest when the matchday ends")
    p.add_argument("--interval", type=int, default=90, help="scheduler poll interval (s)")
    p.add_argument("--report", action="store_true", help="report generated content")
    p.add_argument("--upload", action="store_true", help="upload to YouTube")
    p.add_argument("--social", action="store_true", help="also generate social/blog text")
    p.add_argument("--list", action="store_true", help="list available profiles")
    args = p.parse_args()

    setup_tracing()

    if args.list or not args.profile:
        print("Profiles:")
        for prof in list_profiles():
            print(f"  - {prof['id']}: {prof['name']}")
        if not args.profile:
            return

    cfg = BrandProfile(args.profile)

    if args.fixtures:
        cmd_fixtures(cfg)
    elif args.match:
        cmd_match(cfg, args.match, args.upload, args.social)
    elif args.scheduler:
        cmd_scheduler(cfg, args.interval, args.upload)
    elif args.report:
        cmd_report(cfg)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
