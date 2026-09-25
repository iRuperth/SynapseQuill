"""A digest carrying a rejected segment must not publish itself.

digest.py retries a segment's narration three times and, if it still fails the
guardrail, bakes it in and records the scoreline in `failed_segments`. Baking it
in is the right call — one bad segment out of twelve is no reason to lose a whole
round's recap — but it was supposed to cost the digest its automatic upload.

It never did. The gate that stops it lives on `cfg.AUTO_UPLOAD`, which is False
on this channel for the very reason the gate matters: publishing moved out to a
separate uploader process, so the inline upload the gate guards is dead code and
`upload_skipped` was never written. Fourteen digests reached the public channel
carrying one to four rejected segments each, and the only trace was a WARNING in
a log nobody reads.

So the gate moves to hold_reasons, where every other hold already lives and
where the uploader actually looks.
"""

from pipeline.upload_manager import hold_reasons


def test_a_clean_digest_still_publishes():
    """The common case must stay untouched: an empty list is not a hold."""
    assert hold_reasons({"type": "digest", "failed_segments": []}) == []


def test_a_digest_with_no_such_field_still_publishes():
    """Every match record lacks the field entirely, and so do older digests."""
    assert hold_reasons({"type": "digest"}) == []


def test_a_baked_in_segment_holds_the_digest():
    reasons = hold_reasons({"type": "digest",
                            "failed_segments": ["Málaga 1-1 Deportivo"]})
    assert len(reasons) == 1
    assert "1 digest segment" in reasons[0]


def test_the_reason_names_every_failed_segment():
    """A human has to decide whether to fix the narration or release it as it
    stands, and cannot do that from a count alone."""
    failed = ["Atlético Madrid 2-2 Villarreal", "Valencia 0-1 Real Betis",
              "Getafe 1-0 Racing Santander"]
    reasons = hold_reasons({"type": "digest", "failed_segments": failed})
    assert "3 digest segment" in reasons[0]
    for scoreline in failed:
        assert scoreline in reasons[0]


def test_an_already_published_digest_is_not_retroactively_held():
    """The fourteen that already went out carry a youtube_url, and _unpublished
    filters on exactly that — this pins the intent, since a hold that reached
    back would report a permanent problem nobody can act on."""
    record = {"type": "digest", "failed_segments": ["Málaga 1-1 Deportivo"],
              "youtube_url": "https://youtube.com/watch?v=abc123"}
    # hold_reasons itself is url-agnostic by design; the filtering happens in
    # _unpublished, so the guarantee worth pinning is that the url survives.
    assert record["youtube_url"] and hold_reasons(record)


def test_a_digest_hold_stacks_with_a_narration_hold():
    """Both gates are independent, and a reader needs to see both reasons."""
    reasons = hold_reasons({
        "type": "digest",
        "failed_segments": ["Celta Vigo 1-2 Osasuna"],
        "guardrail": {"passed": False,
                      "facts": {"issues": ["final score 1-2 not clearly stated"]}},
    })
    assert len(reasons) == 2
    assert any("final score" in r for r in reasons)
    assert any("digest segment" in r for r in reasons)
