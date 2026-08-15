"""
reasoner.py
Grounded answer synthesis and structural contradiction detection powered by:
- Google Gemini API (`GEMINI_API_KEY`) using `gemini-1.5-flash` / `gemini-2.0-flash`
- Fallback grounded synthesizer engine when GEMINI_API_KEY is not configured.
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from config import GEMINI_API_KEY, GEMINI_MODEL
from graph_engine import GraphEngine

# Try loading Google GenAI SDK (google-genai or google.generativeai)
GEMINI_CLIENT = None

if GEMINI_API_KEY:
    try:
        from google import genai
        GEMINI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
        USE_NEW_GENAI = True
        print(f"[Reasoner] Initialized Google Gemini API client with model {GEMINI_MODEL}")
    except Exception as e:
        try:
            import google.generativeai as genai_legacy
            genai_legacy.configure(api_key=GEMINI_API_KEY)
            GEMINI_CLIENT = genai_legacy.GenerativeModel(GEMINI_MODEL)
            USE_NEW_GENAI = False
            print(f"[Reasoner] Initialized legacy Google GenerativeAI with model {GEMINI_MODEL}")
        except Exception as e2:
            print(f"[Reasoner] Could not initialize Gemini client: {e2}")
            GEMINI_CLIENT = None


from evidence import EvidenceBuilder, EvidenceSet, EvidenceItem


@dataclass
class Answer:
    query: str
    text: str
    citations: list[str]
    contradictions: list[dict]
    context_node_ids: list[str]
    model_used: str
    evidence_set: dict | None = None


def detect_structural_contradictions(engine: GraphEngine) -> dict:
    """
    Scans graph for Feature nodes with open FeatureRequests ('new', 'in_progress')
    or customer Issues AND a ReleaseNote that ships the feature.
    Returns categorized dict with deduplicated 'confirmed' and 'potential' lists.
    """
    if hasattr(engine, 'neo4j') and getattr(engine.neo4j, 'is_connected', False):
        try:
            return engine.neo4j.detect_contradictions()
        except Exception:
            pass

    confirmed = []
    potential = []
    g = engine.g

    for n, data in g.nodes(data=True):
        if data.get("type") != "Feature":
            continue

        feat_key = data.get("label", n)
        open_frs = []
        potential_frs = []
        issues = []
        ship_releases = []

        for pred in g.predecessors(n):
            pdata = g.nodes[pred]
            ptype = pdata.get("type")
            props = pdata.get("properties", {})
            if ptype == "FeatureRequest":
                st = str(props.get("status", "")).lower()
                if st in ("new", "in_progress", "submitted", "open"):
                    open_frs.append((pred, props))
                elif st in ("reviewing", "backlog", "planned"):
                    potential_frs.append((pred, props))
            elif ptype == "Issue":
                st = str(props.get("status", "")).lower()
                if st in ("open", "in_progress", "investigating"):
                    issues.append((pred, props))
            elif ptype == "ReleaseNote":
                ship_releases.append((pred, props))

        if ship_releases:
            rel_items = [
                {
                    "node_id": r_id,
                    "title": r_props.get("title", r_id),
                    "url": r_props.get("url", r_id)
                } for r_id, r_props in ship_releases
            ]

            # 1. Confirmed Contradiction: Open FR + Released Feature
            if open_frs:
                fr_items = [
                    {
                        "node_id": fr_id,
                        "id": fr_props.get("id", fr_id),
                        "title": fr_props.get("title", feat_key),
                        "status": fr_props.get("status", "open"),
                        "accounts": fr_props.get("accounts", [])
                    } for fr_id, fr_props in open_frs
                ]
                affected_ids = [f"feature:{feat_key}"] + [fr_id for fr_id, _ in open_frs] + [r_id for r_id, _ in ship_releases]

                confirmed.append({
                    "id": f"cntr_conf_{feat_key}",
                    "type": "confirmed",
                    "severity": "HIGH",
                    "feature_key": feat_key,
                    "feature_title": feat_key,
                    "open_feature_requests": fr_items,
                    "shipped_in": rel_items,
                    "affected_node_ids": affected_ids,
                    "description": f"Feature '{feat_key}' has {len(open_frs)} open request(s) ({', '.join(f['id'] for f in fr_items)}), but Release Note '{rel_items[0]['title']}' indicates it has already shipped."
                })

            # 2. Potential Contradiction: Active Issue on Released Feature OR Backlog FR
            elif issues or potential_frs:
                iss_items = [
                    {
                        "node_id": iss_id,
                        "id": iss_props.get("id", iss_id),
                        "title": iss_props.get("title", feat_key),
                        "status": iss_props.get("status", "open"),
                        "account": iss_props.get("account_name")
                    } for iss_id, iss_props in issues
                ]
                pfr_items = [
                    {
                        "node_id": fr_id,
                        "id": fr_props.get("id", fr_id),
                        "title": fr_props.get("title", feat_key),
                        "status": fr_props.get("status", "reviewing"),
                        "accounts": fr_props.get("accounts", [])
                    } for fr_id, fr_props in potential_frs
                ]
                affected_ids = [f"feature:{feat_key}"] + [iss_id for iss_id, _ in issues] + [fr_id for fr_id, _ in potential_frs] + [r_id for r_id, _ in ship_releases]

                desc = f"Feature '{feat_key}' has {len(issues)} active issue(s) reported despite being shipped in '{rel_items[0]['title']}'." if issues else f"Feature '{feat_key}' has {len(potential_frs)} reviewing/backlog request(s) matching release note '{rel_items[0]['title']}'."

                potential.append({
                    "id": f"cntr_pot_{feat_key}",
                    "type": "potential",
                    "severity": "MEDIUM",
                    "feature_key": feat_key,
                    "feature_title": feat_key,
                    "active_issues": iss_items,
                    "potential_feature_requests": pfr_items,
                    "shipped_in": rel_items,
                    "affected_node_ids": affected_ids,
                    "description": desc
                })

    return {
        "confirmed": confirmed,
        "potential": potential,
        "total_confirmed": len(confirmed),
        "total_potential": len(potential)
    }


class Reasoner:
    def __init__(self, engine: GraphEngine, retriever):
        self.engine = engine
        self.retriever = retriever
        self.evidence_builder = EvidenceBuilder(engine)

    def answer(self, query: str, node_type_hints: list[str] | None = None) -> Answer:
        retrieved = self.retriever.hybrid_retrieve(query, top_k=8, node_types=node_type_hints)
        contradictions_dict = detect_structural_contradictions(self.engine)
        all_contradictions = contradictions_dict.get("confirmed", []) + contradictions_dict.get("potential", [])

        evidence_set = self.evidence_builder.build_evidence_set(
            query=query,
            intent="hybrid",
            retrieved_result=retrieved,
            contradictions=all_contradictions,
        )

        citations = evidence_set.citations
        context_node_ids = retrieved.get("node_ids_for_subgraph", [])

        # Build clean prompt context from structured evidence items
        context_lines = []
        for ev in evidence_set.primary_evidence:
            context_lines.append(f"- [{ev.source_type}:{ev.source_id}] (Source: {ev.source_file_or_url}) {ev.snippet}")

        context_block = "\n".join(context_lines)
        contradiction_block = json.dumps(all_contradictions, indent=2) if all_contradictions else "None"

        # If Gemini API client available, synthesize response via Gemini
        if GEMINI_CLIENT and GEMINI_API_KEY:
            try:
                prompt = f"""
You are a Graph-Based Knowledge-Base Assistant for the FlytBase drone autonomy platform.
Answer the user query thoroughly based strictly on the provided Evidence Items (Customer Records and Product Documentation).

User Query: "{query}"

Retrieved Structured Evidence:
{context_block if context_block else "No relevant evidence found."}

Detected Contradictions:
{contradiction_block}

INSTRUCTIONS:
1. Ground EVERY factual claim in the provided context using citations:
   - For customer records: [Customer Record: account_name / issue_id / fr_id / note_id]
   - For doc pages: [Doc Page: https://docs.flytbase.com/...]
   - For release notes: [Release Note: https://releases.flytbase.com/...]
2. If customer requests contradict release notes, explicitly highlight them.
3. If information is missing, explicitly state: "I don't have enough information in the provided context to answer..." and explain what is missing.
"""
                if USE_NEW_GENAI:
                    response = GEMINI_CLIENT.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=prompt,
                    )
                    answer_text = response.text
                else:
                    response = GEMINI_CLIENT.generate_content(prompt)
                    answer_text = response.text

                return Answer(
                    query=query,
                    text=answer_text,
                    citations=citations,
                    contradictions=all_contradictions,
                    context_node_ids=context_node_ids,
                    model_used=f"Google Gemini ({GEMINI_MODEL})",
                    evidence_set=evidence_set.to_dict(),
                )
            except Exception as e:
                print(f"[Reasoner] Gemini generation error ({e}). Using citation-preserving fallback.")

        # Extractive Fallback Synthesizer using EvidenceSet
        sections = []
        if evidence_set.primary_evidence:
            sections.append("### Retrieved Evidence & Citations\n")
            for ev in evidence_set.primary_evidence[:6]:
                sections.append(f"- **[{ev.source_type}: `{ev.source_id}`]** ({ev.source_file_or_url})\n  {ev.snippet}")
        else:
            sections.append("I do not have enough information in the customer data corpus or product documentation to answer this question.")

        if all_contradictions:
            sections.append("\n### ⚠️ Detected Contradictions\n")
            for ctr in all_contradictions[:3]:
                sections.append(f"- {ctr['description']}")

        full_text = "\n".join(sections)
        return Answer(
            query=query,
            text=full_text,
            citations=citations,
            contradictions=all_contradictions,
            context_node_ids=context_node_ids,
            model_used="Grounded Graph Synthesizer (Extractive)",
            evidence_set=evidence_set.to_dict(),
        )
