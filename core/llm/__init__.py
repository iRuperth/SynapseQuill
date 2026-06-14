"""
core.llm — switchable LLM provider layer.

Two ways to talk to an LLM, both honouring LLM_PROVIDER (env or per-profile):

  call_llm(messages, provider=None)  -> str
      Raw text completion via direct REST wrappers. Simple, dependency-light,
      used by the pipeline modules (narrator, content_generator).

  get_llm(provider=None, temperature=...)  -> BaseChatModel
      A LangChain chat model with a built-in fallback chain
      (Groq -> Gemini -> Cerebras), used by the LangGraph agents.

Providers: groq | gemini | cerebras | ollama
"""

import os

from .cerebras import call_cerebras
from .gemini import call_gemini
from .groq import call_groq
from .ollama import call_ollama

_RAW_DISPATCH = {
    "groq": call_groq,
    "gemini": call_gemini,
    "cerebras": call_cerebras,
    "ollama": call_ollama,
}


def call_llm(messages: list, provider: str | None = None, max_tokens: int = 2000,
             timeout: int = 120, label: str = "LLM") -> str:
    """Raw text completion. `messages` is OpenAI-style [{role, content}]."""
    provider = (provider or os.getenv("LLM_PROVIDER", "groq")).lower()
    fn = _RAW_DISPATCH.get(provider)
    if fn is None:
        raise ValueError(f"Unknown LLM provider '{provider}'. "
                         f"Choose from {list(_RAW_DISPATCH)}.")
    return fn(messages, max_tokens=max_tokens, timeout=timeout, label=label)


def get_llm(provider: str | None = None, temperature: float = 0.7):
    """Return a LangChain chat model with a fallback chain, for the agents.

    Imported lazily so that a missing optional dependency for one provider
    does not break the whole module.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "groq")).lower()

    def _build(name: str):
        if name == "groq":
            from langchain_groq import ChatGroq
            return ChatGroq(model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                            temperature=temperature)
        if name == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                                          temperature=temperature)
        if name == "cerebras":
            from langchain_cerebras import ChatCerebras
            return ChatCerebras(model=os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"),
                                temperature=temperature)
        if name == "ollama":
            from langchain_ollama import ChatOllama
            return ChatOllama(model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
                              temperature=temperature)
        raise ValueError(f"Unknown LLM provider '{name}'")

    primary = _build(provider)
    # Build a fallback chain from the remaining configured providers.
    order = ["groq", "gemini", "cerebras", "ollama"]
    fallbacks = []
    for name in order:
        if name == provider:
            continue
        key_present = {
            "groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY",
            "cerebras": "CEREBRAS_API_KEY", "ollama": None,
        }[name]
        if key_present is None or os.getenv(key_present):
            try:
                fallbacks.append(_build(name))
            except Exception:
                pass
    return primary.with_fallbacks(fallbacks) if fallbacks else primary
