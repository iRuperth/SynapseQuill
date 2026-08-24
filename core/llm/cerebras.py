"""Cerebras chat wrapper (OpenAI-compatible)."""

import os

from ._openai_compat import chat_completion

_URL = "https://api.cerebras.ai/v1/chat/completions"
_DEFAULT_MODEL = "gpt-oss-120b"


def call_cerebras(messages: list, max_tokens: int = 2000, timeout: int = 120,
                  label: str = "Cerebras", model: str | None = None) -> str:
    # gpt-oss-120b is a reasoning model: without a low reasoning effort it burns
    # the token budget on hidden reasoning and leaves `content` empty. Keep it
    # minimal so the answer lands in `content`, not `reasoning`.
    return chat_completion(
        url=_URL,
        key_var="CEREBRAS_API_KEY",
        model=model or os.getenv("CEREBRAS_MODEL", _DEFAULT_MODEL),
        messages=messages,
        max_tokens=max_tokens,
        timeout=timeout,
        label=label,
        extra_body={"reasoning_effort": os.getenv("CEREBRAS_REASONING_EFFORT", "low")},
    )
