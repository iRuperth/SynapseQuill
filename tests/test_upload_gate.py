"""What the upload gate holds back, and that it says so out loud.

Every failure here is SILENT in production. A video that a guardrail refuses is
finished, rendered and sitting on disk; nothing raises, nothing retries, and the
uploader's own summary line used to read "every generated video is already
published" while four matches — one of them a 0-5 Barcelona win at Mestalla —
waited behind the gate for days. The only signal anything was wrong was a viewer
noticing a match had never appeared on the channel.

So the gate is pinned from both sides: pending_uploads must never queue a held
record (publishing it would undo the guardrail's decision), and blocked_uploads
must never return it empty-handed (that is what made the hold invisible).
"""

import json

import pytest

from core.brand_config import BrandProfile
from pipeline.upload_manager import blocked_uploads, hold_reasons, pending_uploads


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A throwaway profile whose output dirs are real but empty."""
    monkeypatch.setattr("core.brand_config.PROFILES_DIR", tmp_path)
    (tmp_path / "gate").mkdir()
    (tmp_path / "gate" / "profile.json").write_text(json.dumps({"name": "gate"}))
    return BrandProfile("gate")


def _render(cfg, content_id: str, record: dict) -> None:
    """Write a record AND its .mp4 — the gate ignores a record with no video."""
    (cfg.CONTENT_DIR / f"{content_id}.json").write_text(
        json.dumps(record), encoding="utf-8")
    (cfg.VIDEO_DIR / f"{content_id}.mp4").write_bytes(b"not really an mp4")


# ── What counts as held ──────────────────────────────────────────────
# Each of these is a real record shape taken from a video that was actually
# stuck: the misspelling detector, the grounding judge, the metadata check and
# the generation-time skip are four independent gates and any one of them alone
# is enough to hold a video back.
HELD = [
    ("facts", {"guardrail": {"passed": False,
                             "facts": {"ok": False, "issues": ["'Arnaut' looks like a misspelling"]}}}),
    ("judge", {"guardrail": {"passed": False,
                             "judge": {"grounded": False, "reason": "names a player who did not play"}}}),
    ("metadata", {"metadata_guardrail": {"ok": False, "issues": ["wrong body part"]}}),
    ("skipped", {"upload_skipped": True}),
    # passed:False with no detail at all must STILL be held, never waved through
    # for lack of a reason to print.
    ("bare", {"guardrail": {"passed": False}}),
]


@pytest.mark.parametrize("label,record", HELD, ids=[h[0] for h in HELD])
def test_held_records_are_never_queued(profile, label, record):
    _render(profile, f"match_{label}", record)
    assert pending_uploads(profile) == []


@pytest.mark.parametrize("label,record", HELD, ids=[h[0] for h in HELD])
def test_held_records_are_reported_with_a_reason(profile, label, record):
    """A hold with no reason attached is what made this invisible."""
    _render(profile, f"match_{label}", record)
    blocked = blocked_uploads(profile)
    assert [cid for cid, _ in blocked] == [f"match_{label}"]
    reasons = blocked[0][1]
    assert reasons and all(r.strip() for r in reasons)


def test_a_clean_record_publishes_and_is_not_reported_as_held(profile):
    _render(profile, "match_clean", {"guardrail": {"passed": True},
                                     "metadata_guardrail": {"ok": True}})
    assert pending_uploads(profile) == ["match_clean"]
    assert blocked_uploads(profile) == []


def test_an_already_published_record_is_neither_pending_nor_held(profile):
    """A held record that was later released must not be reported forever."""
    _render(profile, "match_done", {"guardrail": {"passed": False},
                                    "youtube_url": "https://youtube.com/watch?v=x"})
    assert pending_uploads(profile) == []
    assert blocked_uploads(profile) == []


def test_a_record_with_no_rendered_video_is_neither(profile):
    """Nothing to publish and nothing to review — it was never rendered."""
    (profile.CONTENT_DIR / "match_norender.json").write_text(
        json.dumps({"guardrail": {"passed": False}}), encoding="utf-8")
    assert pending_uploads(profile) == []
    assert blocked_uploads(profile) == []


def test_pending_and_blocked_together_account_for_every_rendered_video(profile):
    """The two lists must PARTITION the unpublished set.

    This is the invariant the old code broke: a record could fall out of
    pending_uploads without landing anywhere else, so it existed on disk and in
    no list anyone ever printed.
    """
    _render(profile, "match_clean", {"guardrail": {"passed": True}})
    for label, record in HELD:
        _render(profile, f"match_{label}", record)
    seen = set(pending_uploads(profile)) | {cid for cid, _ in blocked_uploads(profile)}
    assert seen == {"match_clean", *(f"match_{label}" for label, _ in HELD)}


def test_multiple_failing_gates_each_get_their_own_line(profile):
    """A video failing facts, judge and metadata at once must say all three."""
    reasons = hold_reasons({
        "guardrail": {"passed": False,
                      "facts": {"ok": False, "issues": ["'Valero' misspelled"]},
                      "judge": {"grounded": False, "reason": "wrong minute"}},
        "metadata_guardrail": {"ok": False, "issues": ["wrong body part"]},
    })
    assert len(reasons) == 3
    joined = " ".join(reasons)
    assert "Valero" in joined and "wrong minute" in joined and "body part" in joined


def test_a_passing_guardrail_holds_nothing():
    assert hold_reasons({"guardrail": {"passed": True},
                         "metadata_guardrail": {"ok": True}}) == []
    assert hold_reasons({}) == []


# ── A verdict is not permanent ───────────────────────────────────────
# The gate reads a verdict that was written once, at generation time, and never
# revisited. So a video refused by a check that was LATER FIXED stays refused
# for good: the guardrail improves and the video it wrongly held never finds
# out. Three real videos were stuck exactly there — a Racing 2-1 Alavés recap
# whose score check could not read "Racing de Santander 2, Alavés 1" — with
# their fixes already sitting in the tree.
#
# Re-checking is only safe in one direction, and these pin that: deterministic
# checks re-run against today's data, the LLM judge's opinion stands, and a
# fixture that cannot be fetched leaves the hold exactly where it was.
def _racing(**kw):
    from pipeline.match_monitor import Match
    return Match(fixture_id="laliga-401882881", status="FT",
                 home="Racing Santander", away="Alavés",
                 home_goals=2, away_goals=1, venue="El Sardinero", **kw)


def _stale_hold():
    """A record whose frozen verdict no longer matches its own narration."""
    return {
        "narration": "Final en El Sardinero: Racing de Santander 2, Alavés 1.",
        "metadata": {"title": "Racing Santander 2-1 Alavés", "description": ""},
        "guardrail": {"passed": False,
                      "facts": {"ok": False,
                                "issues": ["final score 2-1 not clearly stated"]},
                      "judge": {"grounded": True}},
    }


@pytest.fixture
def _fixture_source(monkeypatch):
    """Point the data source at one known match."""
    class _Source:
        def fixture(self, fixture_id):
            return _racing()
    monkeypatch.setattr("pipeline.data_sources.get_data_source",
                        lambda cfg: _Source())


def test_a_hold_that_no_longer_applies_is_released(profile, _fixture_source):
    from pipeline.upload_manager import revalidate_held
    _render(profile, "match_laliga-401882881", _stale_hold())

    moved = revalidate_held(profile)
    assert [(cid, after) for cid, _before, after in moved] == [
        ("match_laliga-401882881", [])]
    assert pending_uploads(profile) == ["match_laliga-401882881"]
    assert blocked_uploads(profile) == []


def test_the_release_is_written_to_the_record(profile, _fixture_source):
    """Persisted, not just returned — the next run reads the file, not us."""
    from pipeline.upload_manager import revalidate_held
    _render(profile, "match_laliga-401882881", _stale_hold())
    revalidate_held(profile)

    rec = json.loads((profile.CONTENT_DIR / "match_laliga-401882881.json")
                     .read_text(encoding="utf-8"))
    assert rec["guardrail"]["passed"] is True
    assert rec["revalidated_at"]


def test_the_judges_verdict_is_never_re_rolled(profile, _fixture_source):
    """An ungrounded narration stays held even when every deterministic check
    now passes. Re-running the judge costs a call and could flip on model drift
    alone — an opinion is not something to re-roll until it agrees."""
    from pipeline.upload_manager import revalidate_held
    record = _stale_hold()
    record["guardrail"]["judge"] = {"grounded": False,
                                    "reason": "names a player who did not play"}
    _render(profile, "match_judged", record)

    revalidate_held(profile)
    assert pending_uploads(profile) == []
    assert [cid for cid, _ in blocked_uploads(profile)] == ["match_judged"]


def test_a_generation_time_skip_is_never_revalidated(profile, _fixture_source):
    """upload_skipped is a decision, not a check with a right answer."""
    from pipeline.upload_manager import revalidate_held
    record = _stale_hold()
    record["upload_skipped"] = True
    _render(profile, "match_skipped", record)

    assert revalidate_held(profile) == []
    assert pending_uploads(profile) == []


def test_an_unreachable_data_source_keeps_the_hold(profile, monkeypatch):
    """Failing closed is the only safe direction: releasing a video because the
    data that would contradict it is missing is how a wrong match gets out."""
    from pipeline.upload_manager import revalidate_held

    def _broken(cfg):
        raise RuntimeError("ESPN unreachable")
    monkeypatch.setattr("pipeline.data_sources.get_data_source", _broken)
    _render(profile, "match_laliga-401882881", _stale_hold())

    assert revalidate_held(profile) == []
    assert [cid for cid, _ in blocked_uploads(profile)] == ["match_laliga-401882881"]
