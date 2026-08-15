"""
evidence.py
Phase 10 Evidence Layer Implementation.

Transforms raw vector search hits and graph-neighborhood nodes into structured
EvidenceItem and EvidenceSet data objects. Ensures every factual claim sent to
the LLM or answer synthesizer is explicitly attached to a customer record,
documentation URL, timestamp, and source file metadata.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, List, Dict, Optional

from graph_engine import GraphEngine, Node


@dataclass
class EvidenceItem:
    claim_or_topic: str
    source_type: str  # "customer_record" | "documentation" | "release_note"
    source_id: str
    source_file_or_url: str
    snippet: str
    timestamp: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceSet:
    query: str
    intent: str
    primary_evidence: List[EvidenceItem] = field(default_factory=list)
    expanded_evidence: List[EvidenceItem] = field(default_factory=list)
    contradictions: List[dict] = field(default_factory=list)

    @property
    def citations(self) -> List[str]:
        seen = set()
        out = []
        for item in self.primary_evidence + self.expanded_evidence:
            ref = item.source_id if item.source_id.startswith("http") else f"{item.source_type}:{item.source_id}"
            if ref not in seen:
                seen.add(ref)
                out.append(ref)
        return out

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "intent": self.intent,
            "primary_evidence": [e.to_dict() for e in self.primary_evidence],
            "expanded_evidence": [e.to_dict() for e in self.expanded_evidence],
            "contradictions": self.contradictions,
            "citations": self.citations,
        }


class EvidenceBuilder:
    def __init__(self, engine: GraphEngine):
        self.engine = engine

    def build_item(self, node: Node, score: float = 1.0, topic: str = "") -> EvidenceItem:
        p = node.properties
        ntype = node.type

        if ntype in ("DocPage", "ReleaseNote"):
            source_type = "release_note" if ntype == "ReleaseNote" else "documentation"
            url = p.get("url") or node.id.replace("doc:", "")
            snippet = f"{node.label}: {p.get('content', '')[:300]}"
            return EvidenceItem(
                claim_or_topic=topic or node.label,
                source_type=source_type,
                source_id=url,
                source_file_or_url=url,
                snippet=snippet,
                timestamp=p.get("last_fetched_at"),
                metadata={"title": node.label, "score": score, "url": url},
            )

        # Customer record nodes
        source_file = p.get("source_file", "")
        source_row = p.get("source_row", 0)
        source_ref = f"{source_file}:L{source_row}" if source_file and source_row else source_file or "customer_data"
        rec_id = p.get("id") or node.id.split(":", 1)[-1]

        if ntype == "Issue":
            snippet = f"Issue {rec_id} [{p.get('category')}, {p.get('status')}]: {node.label} (Account: {p.get('account_name')})"
        elif ntype == "Task":
            snippet = f"Task {rec_id} [{p.get('priority')}, {p.get('status')}]: {node.label} (Assignee: {p.get('assignee')}, Account: {p.get('account_name')})"
        elif ntype == "FeatureRequest":
            snippet = f"Feature Request {rec_id} [{p.get('product_area')}, {p.get('status')}]: {node.label} (Impact: ${p.get('revenue_impact')})"
        elif ntype == "MeetingNote":
            actions = "; ".join(p.get("action_items", []))
            snippet = f"Meeting {rec_id} ({p.get('date')}): {node.label}. Actions: {actions}"
        elif ntype == "Account":
            snippet = f"Account {node.label} [{p.get('tier')} tier, {p.get('industry')}, ARR ${p.get('arr')}]"
        else:
            snippet = f"{ntype} {node.label}"

        return EvidenceItem(
            claim_or_topic=topic or node.label,
            source_type="customer_record",
            source_id=rec_id,
            source_file_or_url=source_ref,
            snippet=snippet,
            timestamp=p.get("ingested_at"),
            metadata={
                "node_type": ntype,
                "node_id": node.id,
                "account_name": p.get("account_name") or p.get("name"),
                "score": score,
                "source_file": source_file,
                "source_row": source_row,
            },
        )

    def build_evidence_set(
        self,
        query: str,
        intent: str,
        retrieved_result: dict,
        contradictions: list[dict] | None = None,
    ) -> EvidenceSet:
        primary_items: list[EvidenceItem] = []
        expanded_items: list[EvidenceItem] = []

        for p in retrieved_result.get("primary", []):
            node = self.engine.get_node(p["node_id"])
            if node:
                primary_items.append(self.build_item(node, score=p.get("score", 1.0), topic=query))

        for exp in retrieved_result.get("expanded_context", []):
            node = self.engine.get_node(exp["node_id"])
            if node:
                expanded_items.append(self.build_item(node, score=0.5, topic=query))

        return EvidenceSet(
            query=query,
            intent=intent,
            primary_evidence=primary_items,
            expanded_evidence=expanded_items,
            contradictions=contradictions or [],
        )


if __name__ == "__main__":
    from customer_ingest import ingest_all
    from graph_engine import build_customer_graph

    data = ingest_all()
    eng = GraphEngine(reset=True)
    build_customer_graph(eng, data)
    builder = EvidenceBuilder(eng)

    sample_node = eng.get_node("issue:ISS-0050")
    if sample_node:
        item = builder.build_item(sample_node)
        print("Sample EvidenceItem:", item.to_dict())
