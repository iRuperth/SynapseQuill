"""
Shared helper for OpenAI-compatible chat APIs (Groq, Cerebras, ...).

Implements automatic API-key rotation on HTTP 429, mirroring the
key-rotation pattern from Synapse Core's core/cerebras.py.
"""

import os
import time

import requests


def _load_keys(base_var: str) -> list[str]:
    """Collect BASE, BASE_2, BASE_3 ... from the environment."""
    keys = []
    main = os.getenv(base_var, "")
    if main:
        keys.append(main)
    for i in range(2, 20):
        k = os.getenv(f"{base_var}_{i}", "")
        if k:
            keys.append(k)
    return keys


# Per-provider rotating index, keyed by base env-var name.
_idx: dict[str, int] = {}


def chat_completion(*, url: str, key_var: str, model: str, messages: list,
                    max_tokens: int, timeout: int, label: str,
                    extra_body: dict | None = None) -> str:
    """Call an OpenAI-compatible /chat/completions endpoint with key rotation."""
    keys = _load_keys(key_var)
    if not keys:
        raise RuntimeError(f"No {key_var} found in environment / .env")

    _idx.setdefault(key_var, 0)
    resp = None
    attempts = len(keys) * 2
    # A provider that rejects one of our optional knobs (reasoning_effort and
    # friends differ per model family) should cost one retry, not the call.
    drop_extra = False
    attempt = -1
    while attempt + 1 < attempts:
        attempt += 1
        key = keys[_idx[key_var] % len(keys)]
        body = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if extra_body and not drop_extra:
            body.update(extra_body)
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json=body,
            timeout=timeout,
        )
        if resp.status_code == 429:
            _idx[key_var] += 1
            last_attempt = attempt == attempts - 1
            if _idx[key_var] % len(keys) == 0 and attempt > 0:
                # Only wait if another attempt will actually use the wait. On the
                # final pass the caller's fallback chain is the better move: the
                # next model has its own per-model quota and answers now, whereas
                # sleeping here just delays the same 429 by half a minute.
                if last_attempt:
                    print(f"[{label}] All {key_var} keys rate-limited — handing "
                          f"over to the fallback chain")
                    break
                wait = float(os.getenv("LLM_RATELIMIT_WAIT", "20"))
                print(f"[{label}] All {key_var} keys rate-limited, waiting {wait:g}s...")
                time.sleep(wait)
            else:
                print(f"[{label}] {key_var} rate-limited, rotating key "
                      f"{(_idx[key_var] % len(keys)) + 1}/{len(keys)}")
            continue
        # Some models reject an optional knob outright ("`reasoning_effort` is
        # not supported with this model"). Retry once plain before giving up, so
        # adding a model to the chain never needs a code change here.
        if (resp.status_code == 400 and extra_body and not drop_extra
                and any(k in resp.text for k in extra_body)):
            print(f"[{label}] '{model}' rejected {list(extra_body)} — retrying without it")
            drop_extra = True
            attempts += 1        # the reshaped body deserves a real attempt
            continue
        if not resp.ok:
            raise requests.HTTPError(
                f"{label} API {resp.status_code} for model '{model}': {resp.text}",
                response=resp,
            )
        choice = resp.json()["choices"][0]
        msg = choice.get("message", {})
        text = (msg.get("content") or msg.get("reasoning") or "").strip()
        if not text:
            raise RuntimeError(
                f"{label} returned empty content for '{model}' "
                f"(finish_reason={choice.get('finish_reason')}). Try a higher max_tokens."
            )
        # A response cut off at the ceiling is never publishable: every caller
        # here sizes its budget to finish, so "length" means the narration lost
        # its final score or the judge lost its closing brace. Treat it as a
        # failure so the fallback chain tries another model, rather than handing
        # half a script to the guardrail — which would spend a regeneration
        # attempt rejecting prose that was never complete to begin with.
        if choice.get("finish_reason") == "length":
            raise RuntimeError(
                f"{label} truncated at max_tokens for '{model}' "
                f"({len(text.split())} words). Not usable."
            )
        return text

    if resp is not None:
        resp.raise_for_status()
    raise RuntimeError(f"{label} failed after retries")
