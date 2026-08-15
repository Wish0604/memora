"""
query_router.py
Classifies an incoming user query and decomposes it into retrieval
sub-queries. Classification is rule/keyword based (fast, transparent,
zero extra LLM round-trip) with a fallback "combined" bucket so nothing
is ever mis-routed into total silence.

Categories:
  - customer    : about accounts/issues/tasks/meetings/feature requests only
  - docs        : about product docs / plans / release notes only
  - both        : needs fusion across customer + docs graphs
  - analytical  : aggregate / "most requested" / "count by" / "top N" style
  - temporal    : "since when" / "last quarter" / date-range style
"""
from __future__ import annotations
import re
from dataclasses import dataclass

DOCS_KEYWORDS = [
    "supported", "plan", "version", "release", "documentation", "docs",
    "since when", "changelog", "available on", "shipped", "rolled out",
]
ANALYTICAL_KEYWORDS = [
    "most requested", "top ", "count", "how many", "by industry", "by tier",
    "arr impact", "revenue impact", "aggregate", "breakdown", "rank",
]
TEMPORAL_KEYWORDS = [
    "last quarter", "last month", "since", "between", "this week",
    "date", "when did", "timeline", "recent", "upcoming",
]
CONTRADICTION_KEYWORDS = [
    "contradiction", "already released", "already shipped", "conflict",
    "inconsistent", "already available", "duplicate",
]
CUSTOMER_ENTITY_KEYWORDS = [
    "account", "issue", "ticket", "task", "meeting", "feature request",
    "customer", "requested", "arr", "tier", "owner",
]


@dataclass
class RoutedQuery:
    raw_query: str
    intent: str  # customer | docs | both | analytical | temporal | contradiction
    sub_queries: list[str]
    node_type_hints: list[str]


def _contains_any(text: str, keywords: list[str]) -> bool:
    for kw in keywords:
        pattern = r"\b" + re.escape(kw).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, text):
            return True
    return False


def classify(query: str) -> str:
    q = query.lower()
    if _contains_any(q, CONTRADICTION_KEYWORDS):
        return "contradiction"
    if _contains_any(q, ANALYTICAL_KEYWORDS):
        return "analytical"
    if _contains_any(q, TEMPORAL_KEYWORDS):
        return "temporal"
    has_docs = _contains_any(q, DOCS_KEYWORDS)
    has_customer = _contains_any(q, CUSTOMER_ENTITY_KEYWORDS)
    if has_docs and has_customer:
        return "both"
    if has_docs:
        return "docs"
    if has_customer:
        return "customer"
    return "both"  # safe default: search everything rather than under-retrieve


def decompose(query: str, intent: str) -> list[str]:
    """Splits a compound question ('X, and are they on a plan where Y') into
    retrieval-friendly sub-queries. Kept intentionally simple: split on
    common conjunction boundaries, else return the query as a single unit."""
    parts = re.split(r"\band are they\b|\band is (?:it|that)\b|\?\s*and\b|;\s*", query, flags=re.IGNORECASE)
    parts = [p.strip(" ?.,") for p in parts if p.strip(" ?.,")]
    if len(parts) <= 1:
        return [query]
    return parts


def node_type_hints_for_intent(intent: str) -> list[str]:
    if intent == "docs":
        return ["DocPage", "ReleaseNote"]
    if intent == "customer":
        return ["Account", "Issue", "Task", "MeetingNote", "FeatureRequest"]
    if intent == "contradiction":
        return ["FeatureRequest", "ReleaseNote", "DocPage"]
    return []  # both/analytical/temporal: search everything


def route(query: str) -> RoutedQuery:
    intent = classify(query)
    sub_queries = decompose(query, intent)
    hints = node_type_hints_for_intent(intent)
    return RoutedQuery(raw_query=query, intent=intent, sub_queries=sub_queries, node_type_hints=hints)


if __name__ == "__main__":
    tests = [
        "Which accounts have open issues related to live video streaming?",
        "Is live video streaming supported on the Enterprise plan, and since which version?",
        "For accounts that requested better live video streaming, are they on plans where this is already supported according to the docs?",
        "Find feature requests that were already released in FlytBase release notes.",
        "What are the most requested features by industry?",
    ]
    for t in tests:
        r = route(t)
        print(f"\n{t}\n  intent={r.intent}  sub_queries={r.sub_queries}  hints={r.node_type_hints}")
