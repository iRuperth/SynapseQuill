"""A dead key must not end a call while good keys sit behind it.

The rotator was written for HTTP 429 and only for 429: a key that was merely
busy got the next key a turn, and everything else raised on the spot. But 402
"payment required" and 401 "invalid key" are facts about THAT key alone, and the
next one in the keyring may be perfectly good — so the first dead key ended the
call and every key behind it was never tried. Five Cerebras keys sat in .env
while the chain gave up on the first.

It cost nothing the day it was found, because all five keys were equally dead,
and that is exactly why it needed pinning: the bug is invisible until one key
has credit and another does not.

The 429 path deliberately keeps its sleep and its second lap, since a rate limit
really does clear with time. These do not: waiting cannot add credit to an
account or make an invalid key valid, so one lap of the keyring is the whole of
what is worth trying before the caller's fallback chain takes over.
"""

import pytest
import requests

from core.llm import _openai_compat as oc

_URL = "https://example.invalid/v1/chat/completions"


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload or {}
        self.text = text or str(payload or "")

    def json(self):
        return self._payload


_GOOD = {"choices": [{"message": {"content": "OK"}}]}


@pytest.fixture(autouse=True)
def _reset_rotation():
    """The rotating index is module-level, so tests would leak into each other."""
    oc._idx.clear()
    yield
    oc._idx.clear()


def _run(monkeypatch, keys: dict, responder):
    for name, value in keys.items():
        monkeypatch.setenv(name, value)
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        key = (headers or {})["Authorization"].removeprefix("Bearer ")
        calls.append(key)
        return responder(key)
    monkeypatch.setattr(oc.requests, "post", _post)
    # Nothing here should ever sleep: a dead key does not recover by waiting.
    monkeypatch.setattr(oc.time, "sleep",
                        lambda _s: pytest.fail("a dead key must not sleep"))
    out = oc.chat_completion(url=_URL, key_var="T_KEY", model="m",
                             messages=[{"role": "user", "content": "hi"}],
                             max_tokens=10, timeout=5, label="test")
    return out, calls


@pytest.mark.parametrize("status", [401, 402])
def test_a_dead_key_hands_over_to_the_next_one(monkeypatch, status):
    """The case that was silently failing: key one is dead, key two is fine."""
    out, calls = _run(
        monkeypatch,
        {"T_KEY": "dead", "T_KEY_2": "live"},
        lambda k: _Resp(200, _GOOD) if k == "live" else _Resp(status, text="nope"),
    )
    assert out == "OK"
    assert calls == ["dead", "live"], "both keys must be tried, in order"


def test_every_key_in_the_ring_gets_a_turn(monkeypatch):
    out, calls = _run(
        monkeypatch,
        {"T_KEY": "d1", "T_KEY_2": "d2", "T_KEY_3": "d3", "T_KEY_4": "live"},
        lambda k: _Resp(200, _GOOD) if k == "live" else _Resp(402, text="pay"),
    )
    assert out == "OK"
    assert calls == ["d1", "d2", "d3", "live"]


def test_all_keys_dead_raises_rather_than_looping(monkeypatch):
    """One lap, then out. The caller's fallback chain is the next move, and an
    endless retry on an unpayable account is how a scheduler burns a night."""
    with pytest.raises(requests.HTTPError):
        _run(monkeypatch,
             {"T_KEY": "d1", "T_KEY_2": "d2"},
             lambda _k: _Resp(402, text="pay"))


def test_each_key_is_tried_exactly_once(monkeypatch):
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append((headers or {})["Authorization"])
        return _Resp(402, text="pay")
    monkeypatch.setenv("T_KEY", "d1")
    monkeypatch.setenv("T_KEY_2", "d2")
    monkeypatch.setattr(oc.requests, "post", _post)
    monkeypatch.setattr(oc.time, "sleep", lambda _s: None)
    with pytest.raises(requests.HTTPError):
        oc.chat_completion(url=_URL, key_var="T_KEY", model="m",
                           messages=[{"role": "user", "content": "hi"}],
                           max_tokens=10, timeout=5, label="test")
    assert len(calls) == 2, "a dead key is dead for the whole call"


def test_a_single_dead_key_still_raises_immediately(monkeypatch):
    """With one key there is nothing to rotate to, and the old behaviour — raise
    at once so the fallback chain moves on — is still the right one."""
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _Resp(402, text="pay")
    monkeypatch.setenv("T_KEY", "only")
    monkeypatch.setattr(oc.requests, "post", _post)
    with pytest.raises(requests.HTTPError):
        oc.chat_completion(url=_URL, key_var="T_KEY", model="m",
                           messages=[{"role": "user", "content": "hi"}],
                           max_tokens=10, timeout=5, label="test")
    assert len(calls) == 1


def test_a_live_first_key_is_untouched(monkeypatch):
    """No regression for the ordinary case, which is every call on a good day."""
    out, calls = _run(
        monkeypatch,
        {"T_KEY": "live", "T_KEY_2": "spare"},
        lambda _k: _Resp(200, _GOOD),
    )
    assert out == "OK"
    assert calls == ["live"], "a working key must not rotate away"
