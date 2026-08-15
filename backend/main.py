"""
main.py
FastAPI app exposing the Graph-Based Knowledge-Base Agent.

Startup builds (or loads) the dual graph, the vector index, and wires the
reasoner. Endpoints:
  POST /api/query              main conversational query endpoint
  GET  /api/graph/stats        node/edge counts
  POST /api/graph/subgraph     subgraph for the UI visualizer
  POST /api/docs/sync          trigger live crawler sync
  GET  /api/contradictions     structural contradiction list
  GET  /api/analytics          usage signals + graph analytics
"""
from __future__ import annotations
import time
from contextlib import asynccontextmanager

from pathlib import Path

import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from customer_ingest import ingest_all
from graph_engine import GraphEngine, build_customer_graph, build_docs_graph
from docs_crawler import DocsCrawler, get_simulated_crawler
from retriever import HybridRetriever
from query_router import route
from reasoner import Reasoner, detect_structural_contradictions
from usage_signals import UsageSignals, QueryLogEntry

from knowledge.extractor import KnowledgeExtractor
from knowledge.mutation_service import MutationService
from knowledge.schemas import MutationOp, MutationOpType, ProvenanceInfo
from events.event_bus import GLOBAL_EVENT_BUS

STATE: dict = {}


def rebuild_everything(use_live_docs: bool = True):
    print("[main] Initializing Customer Dataset Ingestor...")
    data = ingest_all()
    engine = GraphEngine(reset=True)
    build_customer_graph(engine, data)

    # Initialize Neo4j graph engine if available
    try:
        from graph_engine import Neo4jGraphEngine
        neo4j_engine = Neo4jGraphEngine()
        if neo4j_engine.is_connected:
            neo4j_engine.build_customer_graph(data)
            engine.neo4j = neo4j_engine
    except Exception as e:
        print(f"[main] Neo4j initialization notice: {e}")

    # Crawl docs
    pages = []
    if use_live_docs:
        try:
            print("[main] Attempting live crawler sync for docs.flytbase.com and releases.flytbase.com...")
            crawler = DocsCrawler()
            pages = crawler.sync_all()
            print(f"[main] Live crawler fetched {len(pages)} pages.")
        except Exception as e:
            print(f"[main] Live docs sync failed ({e}), falling back to simulated crawler...")
            pages = []

    if not pages:
        print("[main] Using simulated crawler fixtures...")
        crawler = get_simulated_crawler()
        pages = crawler.sync_all()

    build_docs_graph(engine, pages)
    if hasattr(engine, 'neo4j') and getattr(engine.neo4j, 'is_connected', False):
        engine.neo4j.build_docs_graph(pages)

    engine.persist()

    retriever = HybridRetriever(engine)
    retriever.build_index()

    reasoner = Reasoner(engine, retriever)
    usage = UsageSignals()

    mutation_service = MutationService(engine, event_bus=GLOBAL_EVENT_BUS, retriever=retriever)
    extractor = KnowledgeExtractor()

    STATE["engine"] = engine
    STATE["retriever"] = retriever
    STATE["reasoner"] = reasoner
    STATE["usage"] = usage
    STATE["crawler"] = crawler
    STATE["mutation_service"] = mutation_service
    STATE["extractor"] = extractor



@asynccontextmanager
async def lifespan(app: FastAPI):
    rebuild_everything(use_live_docs=True)
    yield



app = FastAPI(title="Graph-Based Knowledge-Base Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    query: str
    conversation_id: str | None = None


class SubgraphRequest(BaseModel):
    node_ids: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/query")
def api_query(req: QueryRequest):
    start = time.time()

    # 1. Run Knowledge Extraction Pipeline on user interaction
    extracted_ops = STATE["extractor"].extract(req.query, conversation_id=req.conversation_id)
    mutation_info = None
    if extracted_ops:
        mut_res = STATE["mutation_service"].execute_operations(extracted_ops)
        mutation_info = {
            "status": mut_res.status,
            "graph_version": mut_res.graph_version,
            "created_nodes": mut_res.created_nodes,
            "created_edges": mut_res.created_edges,
            "message": mut_res.message,
        }

    # 2. Route & Reason over current Graph State
    routed = route(req.query)

    all_answers = []
    for sub_q in routed.sub_queries:
        ans = STATE["reasoner"].answer(sub_q, node_type_hints=routed.node_type_hints or None)
        all_answers.append(ans)

    combined_text = "\n\n".join(a.text for a in all_answers)
    combined_citations = list({c for a in all_answers for c in a.citations})
    combined_contradictions = [c for a in all_answers for c in a.contradictions]
    combined_node_ids = list({n for a in all_answers for n in a.context_node_ids})
    combined_evidence = [a.evidence_set for a in all_answers if a.evidence_set]

    latency_ms = (time.time() - start) * 1000
    STATE["usage"].log(QueryLogEntry(
        query=req.query, intent=routed.intent, latency_ms=latency_ms,
        citation_count=len(combined_citations), contradiction_count=len(combined_contradictions),
        timestamp=time.time(),
    ))

    return {
        "query": req.query,
        "intent": routed.intent,
        "sub_queries": routed.sub_queries,
        "answer": combined_text,
        "citations": combined_citations,
        "contradictions": combined_contradictions,
        "evidence_set": combined_evidence[0] if len(combined_evidence) == 1 else combined_evidence,
        "graph_node_ids": combined_node_ids,
        "latency_ms": round(latency_ms, 1),
        "mutation_info": mutation_info,
    }


@app.post("/api/knowledge/mutate")
def api_knowledge_mutate(req: dict):
    ops_raw = req.get("operations", [])
    conv_id = req.get("conversation_id")
    ops = []
    for op_dict in ops_raw:
        try:
            op_type = MutationOpType(op_dict.get("type"))
            ops.append(MutationOp(
                op_type=op_type,
                entity_type=op_dict.get("entity_type", "Issue"),
                properties=op_dict.get("properties", {}),
                relationships=op_dict.get("relationships", []),
                provenance=ProvenanceInfo(conversation_id=conv_id, source_type="api")
            ))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid operation payload: {e}")

    res = STATE["mutation_service"].execute_operations(ops)
    return {
        "status": res.status,
        "graph_version": res.graph_version,
        "created_nodes": res.created_nodes,
        "created_edges": res.created_edges,
        "message": res.message,
    }


@app.get("/api/graph/events")
async def api_graph_events():
    queue = GLOBAL_EVENT_BUS.register_async_queue()
    async def event_generator():
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except Exception:
            pass
        finally:
            GLOBAL_EVENT_BUS.unregister_async_queue(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/graph/version")
def api_graph_version():
    return {
        "graph_version": STATE["mutation_service"].version,
        "engine": STATE["engine"].__class__.__name__
    }


@app.get("/api/graph")
def api_get_full_graph(limit: int = 400):
    return STATE["engine"].get_full_graph(max_nodes=limit)


@app.get("/api/graph/stats")
def api_graph_stats():
    return STATE["engine"].stats()


@app.post("/api/graph/subgraph")
def api_graph_subgraph(req: SubgraphRequest):
    return STATE["engine"].subgraph(req.node_ids)


@app.get("/api/docs")
def api_get_docs():
    doc_nodes = STATE["engine"].nodes_by_type("DocPage") or []
    rel_nodes = STATE["engine"].nodes_by_type("ReleaseNote") or []
    all_docs = []
    for n in doc_nodes + rel_nodes:
        p = n.properties or {}
        source = "releases" if "releases." in n.id or n.type == "ReleaseNote" else "docs"
        all_docs.append({
            "type": n.type,
            "source": source,
            "url": n.id,
            "title": n.label or p.get("title") or n.id,
            "last_fetched": p.get("last_fetched") or p.get("date") or "synced",
            "canonical_features": p.get("canonical_features", []),
        })
    return {"pages": all_docs, "count": len(all_docs)}


@app.post("/api/docs/sync")
def api_docs_sync(use_live: bool = False):
    try:
        crawler = STATE["crawler"]
        try:
            pages = crawler.sync_all(force=True)
        except Exception as e:
            print(f"[main] Live crawl sync notice ({e}), using fallback crawler...")
            sim_crawler = get_simulated_crawler()
            pages = sim_crawler.sync_all()

        build_docs_graph(STATE["engine"], pages)
        STATE["engine"].persist()
        STATE["retriever"].build_index()

        GLOBAL_EVENT_BUS.publish({
            "event": "KNOWLEDGE_GRAPH_UPDATED",
            "graph_version": getattr(STATE.get("mutation_service"), "version", 1),
            "source": "docs_sync"
        })

        return {
            "status": "ok",
            "pages_synced": len(pages),
            "urls": [p.url for p in pages],
            "pages": [
                {
                    "url": p.url,
                    "title": p.title,
                    "source": getattr(p, "source", "docs"),
                    "last_fetched": getattr(p, "last_fetched_at", time.time()),
                    "canonical_features": getattr(p, "canonical_features", [])
                } for p in pages
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/contradictions")
def api_contradictions():
    return detect_structural_contradictions(STATE["engine"])


@app.get("/api/analytics")
def api_analytics():
    engine: GraphEngine = STATE["engine"]
    return {
        "usage": STATE["usage"].summary(),
        "graph_stats": engine.stats(),
        "most_requested_features": engine.most_requested_features(10),
        "issue_counts_by_tier": engine.issue_counts_by_tier(),
        "arr_impact_by_feature": engine.arr_impact_by_feature()[:10],
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
