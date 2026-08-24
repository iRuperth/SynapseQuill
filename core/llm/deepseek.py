"""DeepSeek chat wrapper (OpenAI-compatible).

The one provider here on PAID balance rather than a free tier, which is exactly
what makes it useful as a late chain step: it has no per-minute token wall to
run into on a busy matchday, so it answers when every free bucket is spent.
It is placed after the free steps so normal days still cost nothing.

deepseek-v4-flash is the cheap tier and its Spanish is idiomatic enough for the
narrator (it reaches for 'babazorro' and spells Mendizorroza right); v4-pro is
the same API if a segment ever needs more.
"""

import os

from ._openai_compat import chat_completion

_URL = "https://api.deepseek.com/chat/completions"
_DEFAULT_MODEL = "deepseek-v4-pro"


# v4-flash reasons before answering and charges that thinking to the SAME
# max_tokens budget, so a budget sized for the prose alone yields EMPTY content
# (finish_reason=length), not short content. Worse, the thinking tends to expand
# into whatever ceiling it is given, so a modest bump does not help. Measured on
# the real narrator prompt for an eleven-event match, 23 Aug 2026:
#     flash 4200  -> capped both runs,                    0/2 usable
#     flash 6000  -> 1/2 usable        flash 8000  -> 1/2 usable
#     flash 16000 -> 3/3 in one batch, but still capped once via the real
#                    narrator path — no ceiling makes flash dependable here
#     pro   8000  -> 5/6 usable, reasoning 3452-7763 (a far tighter spread)
# So the model is v4-pro, not the cheaper flash: this is the LAST real step in
# the chain — Cerebras behind it is a dead account — so when it fails, the whole
# narration fails. Reliability is worth more than the price gap on a step that
# only fires once the free Groq budgets are spent.
# What does NOT work: `enable_thinking:false` (accepted, then ignored) and
# `reasoning_effort` (rejected outright).
# 8000 was still short in production: a digest segment (whose prompt carries the
# full facts block on top of the brief) exhausted it and came back empty. The
# ceiling is a cap, not a charge — DeepSeek bills tokens actually used — so the
# floor is set where the reasoning has never reached rather than where it
# usually lands. Any remaining truncation is caught by the finish_reason ==
# "length" guard in _openai_compat, so a cut-off script never reaches the
# guardrail.
_HEADROOM = 3
_FLOOR = 16000


def call_deepseek(messages: list, max_tokens: int = 2000, timeout: int = 120,
                  label: str = "DeepSeek", model: str | None = None) -> str:
    return chat_completion(
        url=_URL,
        key_var="DEEPSEEK_API_KEY",
        model=model or os.getenv("DEEPSEEK_MODEL", _DEFAULT_MODEL),
        messages=messages,
        max_tokens=max(max_tokens * _HEADROOM, _FLOOR),
        timeout=timeout,
        label=label,
    )
