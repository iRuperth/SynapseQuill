"""Cerebras chat wrapper (OpenAI-compatible). Free tier, 1M tokens/day."""

import os

from ._openai_compat import chat_completion

_URL = "https://api.cerebras.ai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.3-70b"


def call_cerebras(messages: list, max_tokens: int = 2000, timeout: int = 120,
                  label: str = "Cerebras") -> str:
    return chat_completion(
        url=_URL,
        key_var="CEREBRAS_API_KEY",
        model=os.getenv("CEREBRAS_MODEL", _DEFAULT_MODEL),
        messages=messages,
        max_tokens=max_tokens,
        timeout=timeout,
        label=label,
    )
