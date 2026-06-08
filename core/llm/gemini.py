"""Google Gemini chat wrapper. Free tier, gemini-2.5-flash.

Uses the generativelanguage REST endpoint so it stays dependency-light and
consistent with the other raw wrappers (the LangChain path lives in get_llm()).
"""

import os

import requests

_DEFAULT_MODEL = "gemini-2.5-flash"


def _to_contents(messages: list) -> tuple[list, str | None]:
    """Map OpenAI-style messages to Gemini `contents` + optional system text."""
    contents, system = [], None
    for m in messages:
        role = m.get("role")
        if role == "system":
            system = m["content"]
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        })
    return contents, system


def call_gemini(messages: list, max_tokens: int = 2000, timeout: int = 120,
                label: str = "Gemini") -> str:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("No GEMINI_API_KEY found in environment / .env")
    model = os.getenv("GEMINI_MODEL", _DEFAULT_MODEL)
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")

    contents, system = _to_contents(messages)
    body = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    resp = requests.post(url, json=body, timeout=timeout)
    if not resp.ok:
        raise requests.HTTPError(f"{label} API {resp.status_code}: {resp.text}", response=resp)
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"{label} returned no text: {data}") from e
