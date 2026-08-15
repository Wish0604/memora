"""
dataset.py
Phase 16 Evaluation Dataset.

Contains benchmark query test cases covering Customer Data, Documentation,
Combined (Both), Analytical, Temporal, and Contradiction detection queries.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class EvalTestCase:
    id: str
    query: str
    expected_intents: List[str]
    expected_keywords: List[str]
    expected_citation_prefix: Optional[str] = None
    min_citations: int = 1


EVALUATION_DATASET: List[EvalTestCase] = [
    # Customer Data Queries
    EvalTestCase(
        id="TC-001",
        query="Which accounts have open issues related to live video streaming?",
        expected_intents=["customer", "both"],
        expected_keywords=["Account", "Issue", "live video streaming"],
        expected_citation_prefix="ISS-",
        min_citations=1,
    ),
    EvalTestCase(
        id="TC-002",
        query="List all tasks assigned to Theo Naidoo for Meridian AgriTech",
        expected_intents=["customer", "both"],
        expected_keywords=["Theo Naidoo", "Meridian AgriTech", "TASK-"],
        expected_citation_prefix="TASK-",
        min_citations=1,
    ),
    # Product Documentation Queries
    EvalTestCase(
        id="TC-003",
        query="Is live video streaming supported on the Enterprise plan, and since which version?",
        expected_intents=["docs", "temporal", "both"],
        expected_keywords=["Enterprise", "supported", "3.2.0"],
        expected_citation_prefix="https://",
        min_citations=1,
    ),
    # Combined (Customer + Docs) Queries
    EvalTestCase(
        id="TC-004",
        query="For accounts that requested live video streaming, are they on plans where this is supported according to the docs?",
        expected_intents=["both"],
        expected_keywords=["Enterprise", "requested", "supported"],
        min_citations=1,
    ),
    # Analytical Queries
    EvalTestCase(
        id="TC-005",
        query="What are the most requested features by revenue impact?",
        expected_intents=["analytical"],
        expected_keywords=["Feature", "revenue impact", "ARR"],
        min_citations=1,
    ),
    # Temporal Queries
    EvalTestCase(
        id="TC-006",
        query="What meeting notes were recorded in June 2026 for Meridian AgriTech?",
        expected_intents=["temporal", "customer", "both"],
        expected_keywords=["MTG-", "2026-06", "Meridian AgriTech"],
        expected_citation_prefix="MTG-",
        min_citations=1,
    ),
    # Contradiction Detection Queries
    EvalTestCase(
        id="TC-007",
        query="Find feature requests that were already released in FlytBase release notes.",
        expected_intents=["contradiction"],
        expected_keywords=["FeatureRequest", "ReleaseNote", "shipped"],
        min_citations=1,
    ),
]
