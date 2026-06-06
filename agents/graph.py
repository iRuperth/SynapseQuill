"""
graph.py — multi-agent supervisor (expert level).

A LangGraph supervisor routes each content request to the right specialised
agent, each with its own LLM, prompt and tools:

    sports_agent    football match content (default for World Cup requests)
    social_agent    blog / X / Instagram / LinkedIn copy
    science_agent   popular-science explanations grounded in arXiv RAG
    finance_agent   market-news content using the Finnhub tool

The supervisor itself runs on a fast, cheap model (Cerebras/Groq). This is the
"send the right case to the right agent" requirement from the briefing.

Requires LLM provider keys at runtime; build_supervisor() is lazy so the rest
of the app imports fine without them.
"""

from core.llm import get_llm
from pipeline.tools.arxiv_rag import as_langchain_tool as science_tool
from pipeline.tools.finance import as_langchain_tool as finance_tool


def _resolve_provider(provider: str | None) -> str:
    """Honour the same precedence as core.llm: explicit arg, else LLM_PROVIDER."""
    import os
    return (provider or os.getenv("LLM_PROVIDER", "groq")).lower()


def build_supervisor(supervisor_provider: str | None = None):
    """Build and compile the multi-agent supervisor graph.

    Every agent (and the router) runs on the resolved provider, so the whole
    graph honours the project's switchable-provider design — it uses whatever
    LLM_PROVIDER (or the explicit arg) points to: groq / cerebras / gemini /
    ollama. Falls back to groq only if nothing is configured.
    """
    from langgraph.prebuilt import create_react_agent
    from langgraph_supervisor import create_supervisor

    prov = _resolve_provider(supervisor_provider)

    sports_agent = create_react_agent(
        get_llm(prov, temperature=0.7), tools=[], name="sports_agent",
        prompt=("You produce exciting, factual football match content for the "
                "FIFA World Cup. Never invent scores or scorers."),
    )

    social_agent = create_react_agent(
        get_llm(prov, temperature=0.8), tools=[], name="social_agent",
        prompt=("You write platform-specific social and blog copy (blog, X, "
                "Instagram, LinkedIn), respecting each platform's length and tone."),
    )

    science_agent = create_react_agent(
        get_llm(prov, temperature=0.3), tools=[science_tool()],
        name="science_agent",
        prompt=("You explain scientific topics for a general audience. ALWAYS call "
                "the science_explain tool to ground your answer in retrieved arXiv "
                "context. Never invent facts or citations."),
    )

    finance_agent = create_react_agent(
        get_llm(prov, temperature=0.4), tools=[finance_tool()],
        name="finance_agent",
        prompt=("You create up-to-date financial market content using the "
                "financial_news tool. Cite real, retrieved figures only."),
    )

    supervisor = create_supervisor(
        agents=[sports_agent, social_agent, science_agent, finance_agent],
        model=get_llm(prov, temperature=0),
        prompt=(
            "You are a router. Read the user's content request and delegate to "
            "exactly one agent:\n"
            "- sports_agent: football / World Cup match summaries and highlights\n"
            "- social_agent: blog posts, tweets, Instagram or LinkedIn copy\n"
            "- science_agent: popular-science explanations\n"
            "- finance_agent: financial markets / stock news\n"
            "Delegate, then return the agent's result."
        ),
    )
    return supervisor.compile()


def route_request(request: str, *, supervisor_provider: str | None = None) -> str:
    """Convenience: run one request through the supervisor and return the text."""
    app = build_supervisor(supervisor_provider)
    result = app.invoke({"messages": [{"role": "user", "content": request}]})
    return result["messages"][-1].content
