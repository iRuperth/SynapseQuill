"""
core.llm — switchable LLM provider layer.

Two ways to talk to an LLM, both honouring LLM_PROVIDER (env or per-profile):

  call_llm(messages, provider=None, model=None)  -> str
      Raw text completion via direct REST wrappers. Simple, dependency-light,
      used by the pipeline modules (narrator, content_generator). On failure it
      walks LLM_FALLBACK_CHAIN, a list of "provider:model" steps.

  get_llm(provider=None, temperature=...)  -> BaseChatModel
      A LangChain chat model with a built-in fallback chain
      (Groq -> Gemini -> Cerebras), used by the LangGraph agents.

Providers: groq | gemini | cerebras | deepseek | ollama
"""

import os

from .cerebras import call_cerebras
from .deepseek import call_deepseek
from .gemini import call_gemini
from .groq import call_groq
from .ollama import call_ollama

_RAW_DISPATCH = {
    "groq": call_groq,
    "gemini": call_gemini,
    "cerebras": call_cerebras,
    "deepseek": call_deepseek,
    "ollama": call_ollama,
}


# Where to go when the chosen model fails. Each step is "provider:model"
# ("groq:qwen/qwen3.6-27b"), or a bare "provider" to use that provider's own
# env-configured model. Two things make this list matter more than it looks:
#
#   · Groq meters tokens-per-minute PER MODEL, so a step that only changes the
#     model still buys a whole fresh budget — which is the usual reason a step
#     is needed at all.
#   · The old code fell back to Groq only when Groq was NOT the primary, so
#     making Groq primary silently left the pipeline with no fallback whatever.
#     A chain has no such blind spot: a step is skipped only when it is the
#     exact provider+model that just failed.
# CAREFUL: a step naming a model its provider no longer serves is not a slower
# fallback, it is a guaranteed 404 that costs a round-trip on every single call.
# Groq moved this Qwen from 3.6 to 3.8 and retired the old id, and the chain went
# on asking for 3.6 — 762 wasted requests in one scheduler log, more than the
# rate-limit errors the chain exists to survive. Verify an id against the
# provider's own /v1/models listing before putting it here; Together did exactly
# the same thing with FLUX.1-schnell.
_DEFAULT_CHAIN = "groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b,deepseek,cerebras"

# Credentials a provider needs before a chain step is worth attempting. Ollama
# is local and needs none.
_KEY_VAR = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY",
            "cerebras": "CEREBRAS_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
            "ollama": None}


def _chain_steps() -> list[tuple[str, str | None]]:
    """Parse LLM_FALLBACK_CHAIN into (provider, model|None) steps."""
    raw = os.getenv("LLM_FALLBACK_CHAIN", _DEFAULT_CHAIN)
    steps = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        # Split on the FIRST colon only: model ids carry slashes and, on some
        # providers, colons of their own ("qwen2.5:7b" on Ollama).
        provider, _, model = part.partition(":")
        provider = provider.strip().lower()
        if provider in _RAW_DISPATCH:
            steps.append((provider, model.strip() or None))
    return steps


def _resolved_model(provider: str, model: str | None) -> str | None:
    """The model a step will really use, so a step that merely repeats the
    primary can be recognised and skipped."""
    if model:
        return model
    return os.getenv({"groq": "GROQ_MODEL", "gemini": "GEMINI_MODEL",
                      "cerebras": "CEREBRAS_MODEL", "deepseek": "DEEPSEEK_MODEL",
                      "ollama": "OLLAMA_MODEL"}[provider])


def call_llm(messages: list, provider: str | None = None, max_tokens: int = 2000,
             timeout: int = 120, label: str = "LLM", model: str | None = None) -> str:
    """Raw text completion. `messages` is OpenAI-style [{role, content}].

    Tries the chosen provider/model, then each step of LLM_FALLBACK_CHAIN until
    one answers. Every failure is a trigger: a dead account (Cerebras answering
    402 once its quota is gone), a rate limit, an empty completion. If the whole
    chain fails we re-raise the ORIGINAL error, which points at the real cause
    rather than at whatever the last step happened to complain about.

    Set LLM_FALLBACK_CHAIN="" to disable the chain entirely.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "groq")).lower()
    fn = _RAW_DISPATCH.get(provider)
    if fn is None:
        raise ValueError(f"Unknown LLM provider '{provider}'. "
                         f"Choose from {list(_RAW_DISPATCH)}.")
    try:
        return fn(messages, max_tokens=max_tokens, timeout=timeout, label=label,
                  model=model)
    except Exception as primary_error:  # noqa: BLE001 — any failure is a fallback trigger
        tried = {(provider, _resolved_model(provider, model))}
        for step_provider, step_model in _chain_steps():
            if _KEY_VAR[step_provider] and not os.getenv(_KEY_VAR[step_provider]):
                continue                       # no credentials for this step
            fingerprint = (step_provider, _resolved_model(step_provider, step_model))
            if fingerprint in tried:
                continue                       # same provider+model that just failed
            tried.add(fingerprint)
            shown = fingerprint[1] or step_provider
            print(f"[{label}] {provider} failed ({primary_error}) — trying {shown}"
                  if len(tried) == 2 else f"[{label}] trying {shown}")
            try:
                return _RAW_DISPATCH[step_provider](
                    messages, max_tokens=max_tokens, timeout=timeout,
                    label=f"{label}/{step_provider}", model=step_model)
            except Exception as step_error:  # noqa: BLE001
                print(f"[{label}] {shown} failed ({step_error})")
        raise primary_error


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
        if name == "deepseek":
            # OpenAI-compatible endpoint, so the OpenAI chat class drives it
            # with only a base_url change — no extra provider package.
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                              base_url="https://api.deepseek.com",
                              api_key=os.getenv("DEEPSEEK_API_KEY"),
                              temperature=temperature)
        if name == "ollama":
            from langchain_ollama import ChatOllama
            return ChatOllama(model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
                              temperature=temperature)
        raise ValueError(f"Unknown LLM provider '{name}'")

    primary = _build(provider)
    # Build a fallback chain from the remaining configured providers.
    order = ["groq", "gemini", "deepseek", "cerebras", "ollama"]
    fallbacks = []
    for name in order:
        if name == provider:
            continue
        key_present = _KEY_VAR[name]
        if key_present is None or os.getenv(key_present):
            try:
                fallbacks.append(_build(name))
            except Exception:
                pass
    return primary.with_fallbacks(fallbacks) if fallbacks else primary
