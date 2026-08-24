"""Groq chat wrapper (OpenAI-compatible). Free tier.

Groq meters tokens-per-minute PER MODEL, so two roles pointed at two different
model ids draw on two independent budgets. That is what makes the narrator and
the guardrail judge able to run back to back on the same free key, and it is
why `model` is an argument here rather than only an env var.
"""

import os

from ._openai_compat import chat_completion

_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "openai/gpt-oss-120b"


def _reasoning_body(model: str) -> dict:
    """The reasoning knob each family accepts — they are NOT interchangeable.

    Verified against the live API on 23 Aug 2026:
      gpt-oss-*        "low" (any effort); without it the budget goes to hidden
                       reasoning and `content` comes back empty
      qwen3*           only "none" or "default" — "low" is a 400
      groq/compound*   rejects the parameter outright — a 400
    Sending the wrong one fails the call, so the family decides, not one env var.
    """
    m = (model or "").lower()
    if "gpt-oss" in m:
        return {"reasoning_effort": os.getenv("GROQ_REASONING_EFFORT", "low")}
    if "qwen" in m:
        return {"reasoning_effort": "none"}
    return {}


def call_groq(messages: list, max_tokens: int = 2000, timeout: int = 120,
              label: str = "Groq", model: str | None = None) -> str:
    model = model or os.getenv("GROQ_MODEL", _DEFAULT_MODEL)
    return chat_completion(
        url=_URL,
        key_var="GROQ_API_KEY",
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        timeout=timeout,
        label=label,
        extra_body=_reasoning_body(model),
    )
