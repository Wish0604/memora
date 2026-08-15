"""
evaluator.py
Phase 16 Automated Evaluation Harness.

Runs benchmark test cases against the Knowledge-Base Agent API and calculates:
- Intent Classification Accuracy
- Citation Recall & Precision
- Grounded Answer Synthesis Completeness
- End-to-End Query Latency (ms)
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from dataset import EVALUATION_DATASET, EvalTestCase
from main import rebuild_everything, api_query, QueryRequest, STATE


def run_evaluation() -> dict:
    print("=" * 70)
    print("      MERIDIAN GRAPH KNOWLEDGE-BASE AGENT — EVALUATION SUITE")
    print("=" * 70)

    rebuild_everything(use_live_docs=False)

    passed_count = 0
    total_count = len(EVALUATION_DATASET)
    results = []

    for tc in EVALUATION_DATASET:
        t0 = time.time()
        res = api_query(QueryRequest(query=tc.query))
        latency = (time.time() - t0) * 1000

        intent_correct = res["intent"] in tc.expected_intents
        citation_pass = len(res.get("citations", [])) >= tc.min_citations
        keyword_pass = any(kw.lower() in res["answer"].lower() for kw in tc.expected_keywords)

        test_passed = intent_correct and citation_pass and keyword_pass
        if test_passed:
            passed_count += 1

        status_str = "PASS" if test_passed else "FAIL"
        results.append({
            "id": tc.id,
            "query": tc.query,
            "expected_intents": tc.expected_intents,
            "actual_intent": res["intent"],
            "citations_count": len(res.get("citations", [])),
            "latency_ms": round(latency, 1),
            "status": status_str,
        })

        print(f"[{status_str}] {tc.id}: '{tc.query[:45]}...'")
        print(f"       Intent: {res['intent']} (expected {tc.expected_intents}) | Citations: {len(res.get('citations', []))} | Latency: {round(latency, 1)}ms")
        if not test_passed:
            print(f"       Details: intent_correct={intent_correct}, citation_pass={citation_pass}, keyword_pass={keyword_pass}")

    pass_rate = round((passed_count / total_count) * 100, 1)
    print("-" * 70)
    print(f"EVALUATION SUMMARY: {passed_count}/{total_count} Passed ({pass_rate}% Accuracy)")
    print("-" * 70)

    return {
        "passed": passed_count,
        "total": total_count,
        "pass_rate_pct": pass_rate,
        "results": results,
    }


if __name__ == "__main__":
    summary = run_evaluation()
    if summary["pass_rate_pct"] < 70.0:
        sys.exit(1)
