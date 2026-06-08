"""
graph_rag.py — knowledge-graph-augmented RAG (expert level).

Uses LangChain's LLMGraphTransformer to extract (subject, predicate, object)
triples from document chunks and stores them in an in-memory NetworkX graph.
At query time, entities mentioned in the question are expanded by graph
neighbourhood to provide factual, relational context alongside the vector RAG.

NetworkX (in-memory) keeps the POC infrastructure-free; Neo4j Community is the
documented upgrade path for persistence and Cypher.
"""

import networkx as nx

from core.llm import get_llm


def build_graph(documents, llm=None) -> nx.DiGraph:
    """Extract triples from documents into a directed NetworkX graph."""
    from langchain_experimental.graph_transformers import LLMGraphTransformer

    transformer = LLMGraphTransformer(llm=llm or get_llm())
    graph_docs = transformer.convert_to_graph_documents(documents)

    g = nx.DiGraph()
    for gd in graph_docs:
        for node in gd.nodes:
            g.add_node(node.id, type=node.type)
        for rel in gd.relationships:
            g.add_edge(rel.source.id, rel.target.id, type=rel.type)
    return g


def neighbours(g: nx.DiGraph, entity: str, hops: int = 1) -> list[str]:
    """Return entities within `hops` of `entity` (case-insensitive match)."""
    match = next((n for n in g.nodes if n.lower() == entity.lower()), None)
    if match is None:
        return []
    return list(nx.ego_graph(g, match, radius=hops).nodes)


def graph_context(g: nx.DiGraph, entities: list[str], hops: int = 1) -> str:
    """Build a textual context block from the graph for the given entities."""
    lines = []
    for ent in entities:
        match = next((n for n in g.nodes if n.lower() == ent.lower()), None)
        if match is None:
            continue
        for _, tgt, data in g.out_edges(match, data=True):
            lines.append(f"{match} —{data.get('type', 'related')}→ {tgt}")
        for src, _, data in g.in_edges(match, data=True):
            lines.append(f"{src} —{data.get('type', 'related')}→ {match}")
    return "\n".join(dict.fromkeys(lines))  # dedupe, keep order
