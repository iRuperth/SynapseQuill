"""
arxiv_rag.py — scientific RAG over arXiv papers (advanced level), optionally
augmented with a knowledge graph (expert level / Graph RAG).

Pipeline: ArxivLoader -> RecursiveCharacterTextSplitter -> local HuggingFace
embeddings (BAAI/bge-small-en-v1.5, free, runs locally) -> Chroma vector store.

In this project the RAG is pointed at SPORTS SCIENCE topics (xG models, ML for
tactics, biomechanics, computer vision in football), so it deepens the same
domain the rest of the app works in instead of being a disconnected feature.

When `use_graph=True`, the retrieved documents are also turned into a small
NetworkX knowledge graph (see graph_rag.py) and the relational context is added
to the prompt — this is the Graph RAG path.

All embeddings are computed locally — no API key, no cost.
"""

import os
from pathlib import Path

# ChromaDB pulls in opentelemetry's gRPC OTLP exporter, whose generated
# *_pb2.py modules were built with an old protoc and crash under the modern
# protobuf this project needs (pinned >=5.29 by google-api-core). The official
# workaround is the pure-Python protobuf parser; it only touches Chroma's
# (unused) telemetry path, so there is no relevant performance cost. Set before
# any protobuf-backed module is imported below.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import hashlib
import re

_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
# Root directory holding one Chroma index PER TOPIC. A single shared index would
# answer every topic from whichever papers were indexed first (e.g. ask about
# "highlight detection" and get only the "xG" papers), so each distinct query
# gets its own sub-index, built on first use and cached afterwards.
_PERSIST_ROOT = Path(os.getenv("CHROMA_DIR", "chroma_arxiv"))


def _topic_dir(query: str) -> Path:
    """A stable per-topic index directory: a readable slug + short hash."""
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40] or "topic"
    digest = hashlib.sha1(query.strip().lower().encode()).hexdigest()[:8]
    return _PERSIST_ROOT / f"{slug}_{digest}"


def _embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=_EMBED_MODEL)


def _load_arxiv_docs(query: str, max_docs: int):
    """Fetch arXiv papers as LangChain Documents.

    Uses the `arxiv` client directly (stable API) instead of LangChain's
    ArxivLoader, which calls the removed `Search.results()` on arxiv>=4 and
    raises "'Search' object has no attribute 'results'".
    """
    import arxiv
    from langchain_core.documents import Document

    client = arxiv.Client(page_size=max_docs, delay_seconds=1, num_retries=3)
    docs = []
    # Plain free-text queries get tokenised into a bag of words, so arXiv returns
    # papers that merely share a common word ("deep learning") on unrelated
    # topics. Restrict the search to the abstract field so the WHOLE phrase has
    # to be on-topic; fall back to the loose query only if that finds nothing.
    for q in (f'abs:"{query}"', f"abs:{query}", query):
        search = arxiv.Search(query=q, max_results=max_docs,
                              sort_by=arxiv.SortCriterion.Relevance)
        results = list(client.results(search))
        if results:
            break
    for r in results:
        citation = f"{r.title} ({r.entry_id})"
        body = f"Title: {r.title}\nAuthors: " + \
            ", ".join(a.name for a in r.authors) + f"\n\n{r.summary}"
        docs.append(Document(page_content=body, metadata={
            "source": r.entry_id, "title": r.title, "citation": citation,
            "published": str(getattr(r, "published", "")),
        }))
    return docs


def build_index(query: str, max_docs: int = 8, persist_dir: Path | None = None):
    """Download arXiv papers for `query`, chunk, embed and persist to Chroma."""
    from langchain_chroma import Chroma
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    persist_dir = persist_dir or _topic_dir(query)
    docs = _load_arxiv_docs(query, max_docs)
    if not docs:
        raise RuntimeError(f"No arXiv papers found for query: {query!r}")
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=150
    ).split_documents(docs)

    persist_dir.mkdir(parents=True, exist_ok=True)
    db = Chroma.from_documents(chunks, _embeddings(), persist_directory=str(persist_dir))
    _clean_stray_root_db()
    return db


def _index_ready(persist_dir: Path) -> bool:
    """True only if a real (non-empty) Chroma index exists at `persist_dir`."""
    db = persist_dir / "chroma.sqlite3"
    return db.exists() and db.stat().st_size > 0


def _clean_stray_root_db() -> None:
    """Remove an empty chroma.sqlite3 left in the ROOT dir.

    Chroma can drop a 0-byte sqlite in the persist root if instantiated against
    it; on chromadb>=1.x opening that file fails with 'no such table: tenants'.
    Deleting it (it holds no data) makes the per-topic indexes work again.
    """
    stray = _PERSIST_ROOT / "chroma.sqlite3"
    try:
        if stray.exists() and stray.stat().st_size == 0:
            stray.unlink()
    except OSError:
        pass


def load_index(persist_dir: Path):
    """Open an existing Chroma index at `persist_dir`."""
    from langchain_chroma import Chroma
    _clean_stray_root_db()
    return Chroma(persist_directory=str(persist_dir), embedding_function=_embeddings())


def retrieve(query: str, k: int = 4, persist_dir: Path | None = None):
    """Return the top-k relevant LangChain Documents for a query's topic index."""
    db = load_index(persist_dir or _topic_dir(query))
    return db.similarity_search(query, k=k)


def _graph_context(topic: str, docs) -> str:
    """Build a Graph-RAG relational context block from the retrieved docs.

    Best-effort: graph extraction uses an LLM and can be slow/fail on the free
    tier, so any error degrades gracefully to "no graph context".
    """
    try:
        from pipeline.tools.graph_rag import build_graph, graph_context
        g = build_graph(docs)
        # Seed entities from the topic words. Keep words >3 chars AND short
        # domain acronyms (xG, AI, VR) that the length filter would otherwise
        # drop — those are often the most relevant graph nodes. graph_context
        # now matches seeds against node ids by substring, so single words hit
        # multi-word nodes like 'Expected Goals'.
        words = [w for w in topic.replace("(", " ").replace(")", " ").split()
                 if len(w) > 3 or (1 < len(w) <= 3 and any(c.isupper() for c in w))]
        ctx = graph_context(g, words, hops=1)
        return ctx
    except Exception:  # noqa: BLE001
        return ""


def explain(topic: str, *, language: str = "es", provider: str | None = None,
            build_if_missing: bool = True, use_graph: bool = True) -> str:
    """Generate a grounded popular-science explanation of `topic` from arXiv.

    With `use_graph=True` the retrieved papers also feed a knowledge graph whose
    relational context is added to the prompt (Graph RAG).
    """
    from core.llm import call_llm

    _clean_stray_root_db()
    persist = _topic_dir(topic)
    if build_if_missing and not _index_ready(persist):
        build_index(topic, persist_dir=persist)
    docs = retrieve(topic, persist_dir=persist)
    context = "\n\n".join(d.page_content for d in docs)

    graph_block = _graph_context(topic, docs) if use_graph else ""

    lang = {"es": "Spanish", "en": "English", "fr": "French", "it": "Italian"}.get(language, "Spanish")
    system = (
        f"You are a science communicator writing in {lang}. Explain the topic for a "
        "general audience using ONLY the provided context from scientific papers. "
        "If a knowledge-graph context is provided, use it for factual relationships. "
        "If the context is insufficient, say so. Do not invent facts or citations."
    )
    user = f"Context from arXiv papers:\n{context}"
    if graph_block:
        user += f"\n\nKnowledge-graph relations:\n{graph_block}"
    user += f"\n\nExplain clearly: {topic}"
    return call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider, max_tokens=900, label="ArxivRAG",
    )


def as_langchain_tool():
    """Return a LangChain tool wrapping `explain`, for the science agent."""
    from langchain_core.tools import tool

    @tool
    def science_explain(topic: str) -> str:
        """Explain a scientific topic for a general audience, grounded in arXiv
        papers (with knowledge-graph context). Use for popular-science requests,
        especially sports-science topics like xG models or biomechanics."""
        return explain(topic, use_graph=True)

    return science_explain
