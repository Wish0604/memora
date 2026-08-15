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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from customer_ingest import ingest_all
from graph_engine import GraphEngine, build_customer_graph, build_docs_graph
from docs_crawler import DocsCrawler, get_simulated_crawler
from retriever import HybridRetriever
from query_router import route
from reasoner import Reasoner, detect_structural_contradictions
from usage_signals import UsageSignals, QueryLogEntry

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

    pages = []
    if use_live_docs:
        try:
            print("[main] Attempting live crawler sync for docs.flytbase.com and releases.flytbase.com...")
            crawler = DocsCrawler(simulate=False)
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

    STATE["engine"] = engine
    STATE["retriever"] = retriever
    STATE["reasoner"] = reasoner
    STATE["usage"] = usage
    STATE["crawler"] = crawler



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


class SubgraphRequest(BaseModel):
    node_ids: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/query")
def api_query(req: QueryRequest):
    start = time.time()
    routed = route(req.query)

    all_answers = []
    for sub_q in routed.sub_queries:
        ans = STATE["reasoner"].answer(sub_q, node_type_hints=routed.node_type_hints or None)
        all_answers.append(ans)

    combined_text = "\n\n".join(a.text for a in all_answers)
    combined_citations = list({c for a in all_answers for c in a.citations})
    combined_contradictions = [c for a in all_answers for c in a.contradictions]
    combined_node_ids = list({n for a in all_answers for n in a.context_node_ids})

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
        "graph_node_ids": combined_node_ids,
        "latency_ms": round(latency_ms, 1),
    }


@app.get("/api/graph/stats")
def api_graph_stats():
    return STATE["engine"].stats()


@app.post("/api/graph/subgraph")
def api_graph_subgraph(req: SubgraphRequest):
    return STATE["engine"].subgraph(req.node_ids)


@app.post("/api/docs/sync")
def api_docs_sync(use_live: bool = False):
    try:
        crawler = STATE["crawler"]
        pages = crawler.sync_all(force=True)
        build_docs_graph(STATE["engine"], pages)
        STATE["engine"].persist()
        STATE["retriever"].build_index()
        return {"status": "ok", "pages_synced": len(pages), "urls": [p.url for p in pages]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/contradictions")
def api_contradictions():
    return {"contradictions": detect_structural_contradictions(STATE["engine"])}


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
