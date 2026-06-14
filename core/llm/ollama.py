"""Ollama chat wrapper. Local, free, no API key (offline fallback)."""

import os

import requests

_DEFAULT_MODEL = "qwen2.5:7b"


def call_ollama(messages: list, max_tokens: int = 2000, timeout: int = 300,
                label: str = "Ollama") -> str:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", _DEFAULT_MODEL)
    resp = requests.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens},
        },
        timeout=timeout,
    )
    if not resp.ok:
        raise requests.HTTPError(f"{label} API {resp.status_code}: {resp.text}", response=resp)
    text = (resp.json().get("message", {}).get("content") or "").strip()
    if not text:
        raise RuntimeError(f"{label} returned empty content for model '{model}'")
    return text
