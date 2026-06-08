"""
arxiv_rag.py — scientific RAG over arXiv papers (advanced level).

Pipeline: ArxivLoader -> RecursiveCharacterTextSplitter -> local HuggingFace
embeddings (BAAI/bge-small-en-v1.5, free, runs locally) -> Chroma vector store.

Used to generate accurate popular-science explanations grounded in real papers.
All embeddings are computed locally — no API key, no cost.
"""

import os
from pathlib import Path

_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
_PERSIST = Path(os.getenv("CHROMA_DIR", "chroma_arxiv"))


def _embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=_EMBED_MODEL)


def build_index(query: str, max_docs: int = 8, persist_dir: Path | None = None):
    """Download arXiv papers for `query`, chunk, embed and persist to Chroma."""
    from langchain_chroma import Chroma
    from langchain_community.document_loaders import ArxivLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    persist_dir = persist_dir or _PERSIST
    docs = ArxivLoader(query=query, load_max_docs=max_docs).load()
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=150
    ).split_documents(docs)

    db = Chroma.from_documents(chunks, _embeddings(), persist_directory=str(persist_dir))
    return db


def load_index(persist_dir: Path | None = None):
    """Open an existing Chroma index."""
    from langchain_chroma import Chroma
    persist_dir = persist_dir or _PERSIST
    return Chroma(persist_directory=str(persist_dir), embedding_function=_embeddings())


def retrieve(query: str, k: int = 4, persist_dir: Path | None = None) -> list[str]:
    """Return the top-k relevant chunks for a query (context strings)."""
    db = load_index(persist_dir)
    return [d.page_content for d in db.similarity_search(query, k=k)]


def explain(topic: str, *, language: str = "es", provider: str | None = None,
            build_if_missing: bool = True) -> str:
    """Generate a grounded popular-science explanation of `topic` from arXiv."""
    from core.llm import call_llm

    persist = _PERSIST
    if build_if_missing and not persist.exists():
        build_index(topic)
    context = "\n\n".join(retrieve(topic))

    lang = {"es": "Spanish", "en": "English", "fr": "French", "it": "Italian"}.get(language, "Spanish")
    system = (
        f"You are a science communicator writing in {lang}. Explain the topic for a "
        "general audience using ONLY the provided context from scientific papers. "
        "If the context is insufficient, say so. Do not invent facts or citations."
    )
    user = f"Context from arXiv papers:\n{context}\n\nExplain clearly: {topic}"
    return call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        provider=provider, max_tokens=900, label="ArxivRAG",
    )
