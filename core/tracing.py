"""
tracing.py — LangSmith tracing activation (advanced level).

Enables end-to-end tracing of every LLM call, tool and agent step when
LANGSMITH_TRACING=true and a LANGSMITH_API_KEY is present. Zero code changes
elsewhere — LangChain/LangGraph pick up these environment variables.

Call `setup_tracing()` once at startup.
"""

import os


def setup_tracing() -> bool:
    """Return True if LangSmith tracing is enabled."""
    if os.getenv("LANGSMITH_TRACING", "false").lower() != "true":
        return False
    if not os.getenv("LANGSMITH_API_KEY"):
        print("[tracing] LANGSMITH_TRACING=true but no LANGSMITH_API_KEY — disabled")
        return False
    # LangChain reads these; mirror the legacy LANGCHAIN_* names too.
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", os.environ["LANGSMITH_API_KEY"])
    os.environ.setdefault("LANGCHAIN_PROJECT",
                          os.getenv("LANGSMITH_PROJECT", "f88tball"))
    print(f"[tracing] LangSmith enabled — project "
          f"'{os.getenv('LANGSMITH_PROJECT', 'f88tball')}'")
    return True
