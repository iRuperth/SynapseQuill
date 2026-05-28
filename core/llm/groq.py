"""Groq chat wrapper (OpenAI-compatible). Free tier, Llama 3.3 70B."""

import os

from ._openai_compat import chat_completion

_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.3-70b-versatile"


def call_groq(messages: list, max_tokens: int = 2000, timeout: int = 120, label: str = "Groq") -> str:
    return chat_completion(
        url=_URL,
        key_var="GROQ_API_KEY",
        model=os.getenv("GROQ_MODEL", _DEFAULT_MODEL),
        messages=messages,
        max_tokens=max_tokens,
        timeout=timeout,
        label=label,
    )
