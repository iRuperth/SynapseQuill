"""A match that finished while the scheduler was down must still get a reel.

poll_finished looks at yesterday and today, which is the right window for a
process that never stops. This one stops constantly — every reboot, every crash,
every closed lid — and a match that finished inside the gap falls out of that
two-day window before anything looks again. Espanyol 1-3 Elche is the one that
proves it: kicked off 19:00Z on 18 September, the machine went down at 22:24 that
night and came back on the 20th, by which point the window was asking for the
19th and the 20th. The match never got its own video and nothing said so — it
survives only as a segment inside its round's digest, which is exactly the shape
of failure this project keeps rediscovering.

So the FIRST pass after a start sweeps a week. These tests pin that it does,
that it stops doing so once a pass succeeds, and that it keeps trying while the
source is still broken.
"""

import main


class _Cfg:
    """Minimal stand-in: cmd_scheduler only reads .id and .CONTENT_DIR."""

    def __init__(self, tmp_path):
        self.id = "laliga_es"
        self.CONTENT_DIR = tmp_path


class _Source:
    name = "fake"

    def __init__(self, fail_times=0):
        self.polled = []          # every `day` argument it was handed, in order
        self.fail_times = fail_times

    def poll_finished(self, processed, day=None):
        self.polled.append(day)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("provider is down")
        return []

    def wants_own_video(self, match):
        return True


def _run_passes(monkeypatch, tmp_path, source, passes=1):
    """Drive cmd_scheduler for `passes` sleeps, then break out.

    KeyboardInterrupt rather than a plain Exception on purpose: the loop catches
    Exception by design, so only a BaseException can end it from the inside
    without being mistaken for a provider failure.
    """
    calls = {"sleeps": 0}

    def _sleep(_seconds):
        calls["sleeps"] += 1
        if calls["sleeps"] >= passes:
            raise KeyboardInterrupt
    monkeypatch.setattr(main.time, "sleep", _sleep)
    monkeypatch.setattr(main, "get_data_source", lambda cfg: source)
    monkeypatch.setattr(main, "run_match", lambda *a, **k: None)
    monkeypatch.setattr(main, "_maybe_run_digest", lambda *a, **k: None)
    try:
        main.cmd_scheduler(_Cfg(tmp_path), interval=120, upload=False)
    except KeyboardInterrupt:
        pass
    return calls


# ── The window itself ────────────────────────────────────────────────
def test_a_normal_pass_leaves_the_window_to_the_source():
    """[None] means yesterday AND today, which the source decides — the steady
    state must not name days itself or it would lose that bucketing logic."""
    assert main._poll_days(False) == [None]


def test_the_catchup_pass_reaches_a_week_back():
    days = main._poll_days(True)
    assert len(days) == main._CATCHUP_DAYS + 1
    assert days == sorted(days), "oldest first, so a round generates in order"


def test_the_catchup_window_covers_a_weekend_outage():
    """The gap that lost a match was just under two days. A week of cover is
    what makes a Friday-to-Monday outage survivable rather than lucky."""
    assert main._CATCHUP_DAYS >= 7


# ── How the flag behaves across passes ───────────────────────────────
def test_the_first_pass_sweeps_the_week(monkeypatch, tmp_path):
    source = _Source()
    _run_passes(monkeypatch, tmp_path, source, passes=1)
    assert source.polled == main._poll_days(True)


def test_later_passes_go_back_to_yesterday_and_today(monkeypatch, tmp_path):
    """The sweep is a catch-up, not the steady state: repeating it every two
    minutes would re-ask a week of fixtures forever."""
    source = _Source()
    _run_passes(monkeypatch, tmp_path, source, passes=2)
    assert source.polled == main._poll_days(True) + [None]


def test_a_failed_catchup_is_retried_rather_than_spent(monkeypatch, tmp_path):
    """An outage that is still going when this starts must not burn the one
    chance to catch up — the flag clears on a pass that COMPLETES, not on a
    pass that was merely attempted."""
    source = _Source(fail_times=1)
    _run_passes(monkeypatch, tmp_path, source, passes=2)
    # First pass raised on its first day; the second pass starts the sweep over.
    assert source.polled[0] == main._poll_days(True)[0]
    assert source.polled[1:] == main._poll_days(True)


def test_a_record_already_on_disk_is_never_regenerated(monkeypatch, tmp_path):
    """What makes the sweep cheap: processed is seeded from the records on disk,
    so a normal restart walks a week and generates nothing."""
    (tmp_path / "match_laliga-401882862.json").write_text("{}", encoding="utf-8")
    seen = {}

    class _WithFixture(_Source):
        def poll_finished(self, processed, day=None):
            seen["processed"] = set(processed)
            return []

    _run_passes(monkeypatch, tmp_path, _WithFixture(), passes=1)
    assert "laliga-401882862" in seen["processed"]
