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


@dataclass
class Answer:
    query: str
    text: str
    citations: list[str]
    contradictions: list[dict]
    context_node_ids: list[str]
    model_used: str


def detect_structural_contradictions(engine: GraphEngine) -> list[dict]:
    """
    Scans graph for Feature nodes with an open FeatureRequest ('new' or 'in_progress')
    AND a ReleaseNote that already ships the feature.
    """
    # If Neo4j engine is active, try calling its Cypher contradiction method
    if hasattr(engine, 'neo4j') and getattr(engine.neo4j, 'is_connected', False):
        try:
            return engine.neo4j.detect_contradictions()
        except Exception:
            pass

    contradictions = []
    g = engine.g

    for n, data in g.nodes(data=True):
        if data.get("type") != "Feature":
            continue

        feat_key = data.get("label", n)
        open_frs = []
        ship_releases = []

        for pred in g.predecessors(n):
            pdata = g.nodes[pred]
            ptype = pdata.get("type")
            if ptype == "FeatureRequest":
                props = pdata.get("properties", {})
                if props.get("status") in ("new", "in_progress"):
                    open_frs.append((pred, props))
            elif ptype == "ReleaseNote":
                props = pdata.get("properties", {})
                ship_releases.append((pred, props))

        if open_frs and ship_releases:
            for fr_id, fr_props in open_frs:
                for rel_id, rel_props in ship_releases:
                    contradictions.append({
                        "feature_key": feat_key,
                        "feature_request_id": fr_props.get("id", fr_id),
                        "feature_title": fr_props.get("title", feat_key),
                        "request_status": fr_props.get("status"),
                        "release_title": rel_props.get("title", rel_id),
                        "release_url": rel_props.get("url", rel_id),
                        "description": f"FeatureRequest {fr_props.get('id')} ('{fr_props.get('title')}') is marked '{fr_props.get('status')}', but ReleaseNote '{rel_props.get('title')}' indicates it has already shipped."
                    })
    return contradictions


class Reasoner:
    def __init__(self, engine: GraphEngine, retriever):
        self.engine = engine
        self.retriever = retriever

    def answer(self, query: str, node_type_hints: list[str] | None = None) -> Answer:
        retrieval = self.retriever.retrieve(query, node_type_hints=node_type_hints)
        citations = retrieval.citations
        context_node_ids = retrieval.graph_node_ids
        all_contradictions = detect_structural_contradictions(self.engine)

        # Build clean prompt context
        context_block = "\n".join([f"- [{c['type']}:{c['id']}] {c['snippet']}" for c in citations])
        contradiction_block = json.dumps(all_contradictions, indent=2) if all_contradictions else "None"

        # If Gemini API client available, synthesize response via Gemini
        if GEMINI_CLIENT and GEMINI_API_KEY:
            try:
                prompt = f"""
You are a Graph-Based Knowledge-Base Assistant for the FlytBase drone autonomy platform.
Answer the user query thoroughly based strictly on the provided Customer Records and Product Documentation.

User Query: "{query}"

Retrieved Context & Citations:
{context_block if context_block else "No relevant context found."}

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
                    citations=[c["id"] for c in citations],
                    contradictions=all_contradictions,
                    context_node_ids=context_node_ids,
                    model_used=f"Google Gemini ({GEMINI_MODEL})"
                )
            except Exception as e:
                print(f"[Reasoner] Gemini generation error ({e}). Using citation-preserving fallback.")

        # Extractive Fallback Synthesizer
        sections = []
        if citations:
            sections.append("### Retrieved Context & Citations\n")
            for c in citations[:6]:
                sections.append(f"- **[{c['type']}: {c['id']}]** {c['snippet']}")
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
            citations=[c["id"] for c in citations],
            contradictions=all_contradictions,
            context_node_ids=context_node_ids,
            model_used="Grounded Graph Synthesizer (Extractive)"
        )
