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

    ONE RECAP PER COMPETITION, not per day. What counts as a round comes from the
    competition preset: a World Cup day is its own recap, while a LaLiga jornada
    spans Friday to Monday and must be ONE recap. So each candidate day is first
    resolved to its round, and the round is keyed by its first day — every day of
    a jornada maps to the same record file, which is what stops a four-day round
    from producing four near-identical digests. Today is excluded so a round is
    only summarised once fully played, and the record file marks it done so it
    never re-generates.

    The competitions are handled SEPARATELY because a channel carrying LaLiga
    (Fri-Mon), the Champions League (Tue-Wed) and the Europa League (Thu) has no
    empty day left in its week. Resolving a round against the whole feed would
    swallow the lot into one seven-day "jornada" mixing four competitions under
    one title. Each competition's round is delimited by its own fixtures.
    """
    from datetime import date, timedelta

    from core import competitions
    from pipeline.digest import fixtures_of, matchday_days, run_daily_digest

    # Which competitions actually played in the look-back window. Derived from
    # the fixtures rather than from the legs, so a competition the feed picked up
    # without a preset of its own still gets a recap instead of being dropped.
    days_back = [(date.today() - timedelta(days=o)).isoformat()
                 for o in range(_DIGEST_LOOKBACK_DAYS, 0, -1)]
    present: dict[str, str] = {}
    for d in days_back:
        for m in source.fixtures_on(d) or []:
            key = competitions.key_for(m.competition)
            # A competition the channel follows a single club in gets no recap:
            # its "round" is that club's one match, which already has a video of
            # its own, so the recap would publish the same game twice.
            if key and competitions.has_round_up(key):
                present.setdefault(key, m.competition)
    if not present:
        return

    for comp_key in present:
        mode = competitions.digest_mode(comp_key)
        keep = _same_competition(comp_key)
        built: set[str] = set()
        # Oldest first, so missed rounds are filled in chronological order. Skip
        # today (offset 0): its games may still be in progress.
        for d in days_back:
            days = matchday_days(source, d, mode, keep)
            anchor = days[0]
            if anchor in built:
                continue                        # same round, already handled
            built.add(anchor)
            if _digest_exists(cfg, anchor, comp_key):
                continue                        # already built
            # A round is only ready when EVERY day of it has games and all of
            # them have finished — including a Monday-night closer still running.
            fixtures = [m for day in days for m in fixtures_of(source, day, keep)]
            if not fixtures or not all(m.is_finished for m in fixtures):
                continue                        # no games / still playing
            print(f"[scheduler] {comp_key} round {anchor} complete "
                  f"({len(fixtures)} matches) over {len(days)} day(s) — "
                  f"building the digest...")
            run_daily_digest(cfg.id, anchor, _DIGEST_FORMAT, upload=upload or None,
                             competition=comp_key,
                             on_step=lambda step, msg: print(f"[digest:{step}] {msg}"))


def _same_competition(comp_key: str):
    """Predicate keeping only the matches of one competition."""
    from core import competitions
    return lambda m: competitions.key_for(m.competition) == comp_key


def _digest_exists(cfg: BrandProfile, anchor: str, comp_key: str) -> bool:
    """True when this round's recap has already been built.

    Also honours the PRE-COMPETITION record name (`digest_<anchor>_<fmt>.json`),
    from when the channel carried a single competition and a round produced
    exactly one recap. Those recaps are already on YouTube; treating their day as
    unbuilt would generate a second copy of a video that is live, so a legacy
    record blocks the anchor outright rather than only its own competition.
    """
    new = cfg.CONTENT_DIR / f"digest_{anchor}_{comp_key}_{_DIGEST_FORMAT}.json"
    legacy = cfg.CONTENT_DIR / f"digest_{anchor}_{_DIGEST_FORMAT}.json"
    return new.exists() or legacy.exists()


# Ceiling for the scheduler's error backoff. Half an hour is long enough that a
# dead provider costs a handful of attempts a day instead of hundreds, and short
# enough that a matchday resuming mid-afternoon is picked up the same afternoon.
_MAX_BACKOFF = 30 * 60


def _backoff(interval: int, failures: int) -> float:
    """Seconds to wait before the next poll: the normal interval while healthy,
    doubling per consecutive failure up to _MAX_BACKOFF."""
    if failures <= 0:
        return interval
    return min(interval * (2 ** failures), _MAX_BACKOFF)


# How far back the FIRST pass after a start looks for matches nobody covered.
# poll_finished sees yesterday and today, which is right for a process that
# never stops — but this one stops for every reboot, every crash and every
# closed laptop lid, and a match that finished inside that gap falls out of the
# two-day window before anything can look at it again. Espanyol 1-3 Elche, kicked
# off 19:00Z on 18 September, is exactly that: the machine went down at 22:24
# that night and came back on the 20th, by which point the window was asking for
# the 19th and the 20th, so the match never got a reel — it survives only as a
# segment inside its round's digest, and nothing anywhere said so.
#
# A week is the span that matters: it covers a weekend outage plus the midweek
# round either side of it, and the sweep is nearly free because `processed` is
# seeded from the records on disk, so a normal restart finds nothing to do and
# generates nothing at all.
_CATCHUP_DAYS = 7


def _poll_days(catchup: bool) -> list:
    """Days to poll on one pass. [None] lets the source use its own default of
    yesterday AND today; the catch-up pass names each day explicitly instead."""
    if not catchup:
        return [None]
    from datetime import date, timedelta
    today = date.today()
    return [(today - timedelta(days=i)).isoformat()
            for i in range(_CATCHUP_DAYS, -1, -1)]


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
    failures = 0
    # The first pass sweeps the last week, so a match that finished while this
    # process was down still gets its reel. Cleared only after a pass completes
    # without raising, so an outage that is still going when we start does not
    # burn the one chance to catch up.
    catchup = True
    while True:
        try:
            if catchup:
                print(f"[scheduler] catching up on the last {_CATCHUP_DAYS} days "
                      f"in case anything finished while this was down...")
            for day in _poll_days(catchup):
                for match in source.poll_finished(processed, day):
                    # A match can belong in the channel without deserving a video
                    # of its own — a first-round cup tie between two clubs nobody
                    # knows is covered by its round's recap and nothing else. Mark
                    # it processed anyway, or every pass would reconsider it
                    # forever.
                    if not source.wants_own_video(match):
                        print(f"[scheduler] {match.scoreline} — round-up only, no reel")
                        processed.add(match.fixture_id)
                        continue
                    where = f" [catch-up {day}]" if day else ""
                    print(f"[scheduler] finished: {match.scoreline}{where} — generating...")
                    run_match(cfg.id, match, do_video=True, do_upload=upload)
            _maybe_run_digest(cfg, source, upload)
            failures = 0
            catchup = False
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"[scheduler] error ({failures} in a row): {e}")
        # Back off while it keeps failing. A match or digest that errors is
        # never recorded as done, so the next pass retries it — which is what we
        # want for a blip, and a quota-burning trap for an outage: every retry
        # of every pending match spends tokens on the SAME failure. Doubling the
        # wait turned six days of polling into a handful of attempts, and kept
        # the free-tier budget available for the retry that can actually work.
        time.sleep(_backoff(interval, failures))


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
