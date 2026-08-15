"""
retriever.py
Semantic vector search + hybrid retriever.

Uses TF-IDF (scikit-learn) rather than sentence-transformers by default —
it needs no model download, indexes ~2.5k short records in milliseconds,
and is more than sufficient for keyword-adjacent customer-support text.
The module is structured so a sentence-transformers backend can be dropped
in later (see `EMBEDDING_BACKEND`) without touching calling code.

Retrieval flow:
  1. Build one text "chunk" per graph node worth searching (Issues, Tasks,
     MeetingNotes, FeatureRequests, DocPages, ReleaseNotes).
  2. Vector top-K via cosine similarity over TF-IDF vectors.
  3. Graph neighborhood expansion: pull in directly connected nodes
     (e.g. the Account an Issue belongs to) so the reasoner has grounding
     context, not just the matched chunk in isolation.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from config import retrieval_config
from graph_engine import GraphEngine, Node

EMBEDDING_BACKEND = "tfidf"  # swap to "sentence-transformers" if desired later

SEARCHABLE_TYPES = ["Issue", "Task", "MeetingNote", "FeatureRequest", "DocPage", "ReleaseNote", "Account"]


@dataclass
class Chunk:
    node_id: str
    node_type: str
    text: str


@dataclass
class RetrievedItem:
    node_id: str
    node_type: str
    score: float
    text: str


def node_to_text(node: Node) -> str:
    """Flattens a node's properties into a single searchable text blob."""
    p = node.properties
    if node.type == "Issue":
        return f"Issue {node.id} [{p.get('category')}, {p.get('status')}]: {node.label}"
    if node.type == "Task":
        return f"Task {node.id} [{p.get('priority')}, {p.get('status')}] assigned to {p.get('assignee')}: {node.label} (due {p.get('due')})"
    if node.type == "MeetingNote":
        actions = "; ".join(p.get("action_items", []))
        return f"Meeting {node.id} on {p.get('date')} — {node.label}. Attendees: {', '.join(p.get('attendees', []))}. Action items: {actions}"
    if node.type == "FeatureRequest":
        return f"Feature request {node.id} [{p.get('product_area')}, {p.get('status')}]: {node.label} ({p.get('mentions')} mentions, est. revenue impact ${p.get('revenue_impact')})"
    if node.type in ("DocPage", "ReleaseNote"):
        return f"{node.type} — {node.label}\n{p.get('content', '')}"
    if node.type == "Account":
        return f"Account {node.label} ({p.get('industry')}, {p.get('region')}, {p.get('tier')} tier, {p.get('health')}, ARR ${p.get('arr')})"
    return node.label


def _chunk_long_text(node_id: str, node_type: str, text: str) -> list[Chunk]:
    size = retrieval_config.chunk_size_chars
    overlap = retrieval_config.chunk_overlap_chars
    if len(text) <= size:
        return [Chunk(node_id, node_type, text)]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(Chunk(node_id, node_type, text[start:end]))
        if end == len(text):
            break
        start = end - overlap
    return chunks


class HybridRetriever:
    def __init__(self, engine: GraphEngine):
        self.engine = engine
        self.chunks: list[Chunk] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None

    def build_index(self):
        self.chunks = []
        for node_type in SEARCHABLE_TYPES:
            nodes = self.engine.nodes_by_type(node_type) or []
            for node in nodes:
                text = node_to_text(node)
                self.chunks.extend(_chunk_long_text(node.id, node.type, text))

        corpus = [c.text for c in self.chunks]
        if not corpus:
            self.vectorizer, self.matrix = None, None
            return
        self.vectorizer = TfidfVectorizer(stop_words="english", max_features=20000, ngram_range=(1, 2))
        self.matrix = self.vectorizer.fit_transform(corpus)

    def vector_search(self, query: str, top_k: int | None = None, node_types: list[str] | None = None) -> list[RetrievedItem]:
        if self.vectorizer is None or self.matrix is None:
            return []
        top_k = top_k or retrieval_config.vector_top_k
        q_vec = self.vectorizer.transform([query])
        sims = cosine_similarity(q_vec, self.matrix)[0]
        order = np.argsort(-sims)

        seen_nodes: set[str] = set()
        results: list[RetrievedItem] = []
        for idx in order:
            score = float(sims[idx])
            if score < retrieval_config.min_similarity:
                break
            chunk = self.chunks[idx]
            if node_types and chunk.node_type not in node_types:
                continue
            if chunk.node_id in seen_nodes:
                continue
            seen_nodes.add(chunk.node_id)
            results.append(RetrievedItem(chunk.node_id, chunk.node_type, score, chunk.text))
            if len(results) >= top_k:
                break
        return results

    def hybrid_retrieve(self, query: str, top_k: int | None = None, node_types: list[str] | None = None, hops: int = None) -> dict:
        """Vector top-K, then graph-neighborhood expansion for grounding context."""
        hops = retrieval_config.graph_hop_expansion if hops is None else hops
        primary = self.vector_search(query, top_k=top_k, node_types=node_types)
        seed_ids = [r.node_id for r in primary]
        expanded_ids = self.engine.multi_hop(seed_ids, hops=hops) if seed_ids else set()

        expanded_nodes = []
        for nid in expanded_ids - set(seed_ids):
            node = self.engine.get_node(nid)
            if node:
                expanded_nodes.append({"node_id": nid, "node_type": node.type, "text": node_to_text(node)})

        return {
            "primary": [r.__dict__ for r in primary],
            "expanded_context": expanded_nodes,
            "node_ids_for_subgraph": list(set(seed_ids) | expanded_ids),
        }


if __name__ == "__main__":
    from customer_ingest import ingest_all
    from graph_engine import build_customer_graph, build_docs_graph
    from docs_crawler import get_simulated_crawler

    data = ingest_all()
    engine = GraphEngine(reset=True)
    build_customer_graph(engine, data)
    build_docs_graph(engine, get_simulated_crawler().sync_all())
    engine.persist()

    retriever = HybridRetriever(engine)
    retriever.build_index()

    for q in [
        "accounts with open issues about live video streaming",
        "is live video streaming supported on the Enterprise plan",
        "camera feed drops during high wind",
    ]:
        print(f"\nQuery: {q}")
        res = retriever.hybrid_retrieve(q, top_k=5)
        for r in res["primary"]:
            print(f"  [{r['score']:.3f}] {r['node_type']} {r['node_id']}: {r['text'][:90]}")
        print(f"  (+{len(res['expanded_context'])} expanded context nodes)")
