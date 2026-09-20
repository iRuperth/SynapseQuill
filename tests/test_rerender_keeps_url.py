"""Re-rendering a match must not republish it.

The content record is rewritten wholesale on every run, and the uploader decides
what is unpublished by exactly one field: youtube_url. So re-generating a match
that is already on the channel dropped its URL, and the next uploader pass —
which runs every sixty seconds — put a SECOND public copy of the same game up.

Nothing downstream can catch that. The two videos have different YouTube ids and
nothing ties them together; the only signal is a viewer scrolling past the same
match twice. It very nearly happened to a Getafe 1-1 Celta recap published on 7
September: a re-render on the 8th wiped the URL, and the only thing standing
between the channel and a duplicate was an unrelated guardrail hold.

Re-rendering does not un-publish anything, and the YouTube API has no call to
replace the file behind an existing video — so the URL is a fact about the
channel that a local render has no business erasing.
"""

import json

from pipeline.runner import _keep_published_url


def _record(path, **fields):
    path.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")


def test_a_published_url_survives_a_re_render(tmp_path):
    out = tmp_path / "match_laliga-401882891.json"
    _record(out, youtube_url="https://youtube.com/watch?v=WITrv1c5pGo",
            youtube_privacy="public", narration="la primera versión")

    fresh = {"narration": "la versión re-renderizada"}
    _keep_published_url(out, fresh)

    assert fresh["youtube_url"] == "https://youtube.com/watch?v=WITrv1c5pGo"
    assert fresh["youtube_privacy"] == "public"
    assert fresh["re_rendered_after_publishing"] is True


def test_a_fresh_upload_url_is_never_overwritten(tmp_path):
    """A run that uploaded for itself keeps ITS url, not the old one."""
    out = tmp_path / "match_laliga-401882891.json"
    _record(out, youtube_url="https://youtube.com/watch?v=OLD")

    fresh = {"youtube_url": "https://youtube.com/watch?v=NEW"}
    _keep_published_url(out, fresh)
    assert fresh["youtube_url"] == "https://youtube.com/watch?v=NEW"


def test_a_never_published_match_gains_nothing(tmp_path):
    out = tmp_path / "match_laliga-401882881.json"
    _record(out, narration="generado pero nunca subido")

    fresh = {"narration": "regenerado"}
    _keep_published_url(out, fresh)
    assert "youtube_url" not in fresh


def test_a_first_render_has_no_previous_record(tmp_path):
    fresh = {"narration": "la primera vez"}
    _keep_published_url(tmp_path / "match_new.json", fresh)
    assert "youtube_url" not in fresh


def test_an_unreadable_record_is_not_fatal(tmp_path):
    """A corrupt record must not take the whole generation run down with it."""
    out = tmp_path / "match_broken.json"
    out.write_text("{not json", encoding="utf-8")

    fresh = {"narration": "regenerado"}
    _keep_published_url(out, fresh)
    assert "youtube_url" not in fresh
