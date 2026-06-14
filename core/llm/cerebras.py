"""Cerebras chat wrapper (OpenAI-compatible). Free tier, 1M tokens/day."""

import os

from ._openai_compat import chat_completion

_URL = "https://api.cerebras.ai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.3-70b"


def call_cerebras(messages: list, max_tokens: int = 2000, timeout: int = 120,
                  label: str = "Cerebras") -> str:
    # gpt-oss-120b is a reasoning model: without a low reasoning effort it burns
    # the token budget on hidden reasoning and leaves `content` empty. Keep it
    # minimal so the answer lands in `content`, not `reasoning`.
    return chat_completion(
        url=_URL,
        key_var="CEREBRAS_API_KEY",
        model=os.getenv("CEREBRAS_MODEL", _DEFAULT_MODEL),
        messages=messages,
        max_tokens=max_tokens,
        timeout=timeout,
        label=label,
        extra_body={"reasoning_effort": os.getenv("CEREBRAS_REASONING_EFFORT", "low")},
    )
