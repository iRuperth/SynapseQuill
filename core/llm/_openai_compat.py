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
    for attempt in range(len(keys) * 2):
        key = keys[_idx[key_var] % len(keys)]
        body = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if extra_body:
            body.update(extra_body)
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json=body,
            timeout=timeout,
        )
        if resp.status_code == 429:
            _idx[key_var] += 1
            if _idx[key_var] % len(keys) == 0 and attempt > 0:
                print(f"[{label}] All {key_var} keys rate-limited, waiting 30s...")
                time.sleep(30)
            else:
                print(f"[{label}] {key_var} rate-limited, rotating key "
                      f"{(_idx[key_var] % len(keys)) + 1}/{len(keys)}")
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
        return text

    if resp is not None:
        resp.raise_for_status()
    raise RuntimeError(f"{label} failed after retries")
