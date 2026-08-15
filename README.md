# Meridian — Graph-Based Knowledge-Base Agent

A working implementation of the plan in `Implementation Plan: Graph-Based
Knowledge-Base Agent`, built layer by layer against the real synthetic
dataset (51 accounts, 961 issues, 55 feature requests, 473 tasks, 276
meeting notes).

## Layers, in build order

| # | File | What it does | Verified with |
|---|---|---|---|
| 1 | `backend/config.py` | Paths, doc URLs, cache TTLs, canonical feature-name keyword map | imported everywhere |
| 2 | `backend/customer_ingest.py` | Parses all 5 markdown datasets into typed entities | `python3 customer_ingest.py` → 51/961/55/473/276/637 parsed |
| 3 | `backend/graph_engine.py` | NetworkX + SQLite dual-graph store, traversal, analytics | `python3 graph_engine.py` → 2,483 nodes / 3,170 edges |
| 4 | `backend/docs_crawler.py` | `llms.txt`-driven crawler with content-hash caching | `python3 docs_crawler.py` (simulate mode — see note below) |
| 5 | `backend/retriever.py` | TF-IDF vector search + graph-neighborhood expansion | `python3 retriever.py` — correctly surfaces docs *and* customer records for a mixed query |
| 6 | `backend/query_router.py` | Keyword-based intent classifier + sub-query decomposer | `python3 query_router.py` — correctly classifies all 4 demo query types |
| 7 | `backend/reasoner.py` | Grounded synthesis, citation extraction, structural contradiction detection | `python3 reasoner.py` |
| 8 | `backend/usage_signals.py` | SQLite-backed query logging | exercised via `/api/analytics` |
| 9 | `backend/main.py` | FastAPI app wiring every layer + serving the frontend | `uvicorn main:app` |
| 10 | `frontend/` | Chat UI, D3 force-directed graph explorer, contradiction board, doc sync inspector, analytics dashboard | manual browser check |

## Running it

```bash
cd backend
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...   # optional — see note below
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000/` — the FastAPI app serves the frontend
directly (`StaticFiles` mount) alongside the `/api/*` endpoints, so there's
nothing extra to stand up.

### No Anthropic API key? It still works.
`reasoner.py` falls back to a citation-preserving **extractive** answer
(joins the retrieved, cited context directly) if `ANTHROPIC_API_KEY` isn't
set or the `anthropic` package isn't installed. Set the key to get real
LLM-synthesized prose answers instead of the raw extracted bullets.

### About live doc fetching
`docs_crawler.py` is written to hit `docs.flytbase.com/llms.txt` and
`releases.flytbase.com/llms.txt` for real. In *this* sandbox's network
allow-list those domains aren't reachable, so `main.py` defaults to
`get_simulated_crawler()`, which uses small representative fixture pages
(same shape: an `llms.txt` manifest + a few markdown pages) so every layer
downstream — graph fusion, contradiction detection, citations — runs
against realistic data end to end. Flip `use_live_docs=True` in
`rebuild_everything()` (or call `POST /api/docs/sync?use_live=true`) once
deployed somewhere that can reach those domains; no other code changes
needed.

## What's actually demonstrated end-to-end

- **Customer-only**: "Which accounts have open issues related to live
  video streaming?" → pulls matching `Issue` nodes + their linked `Account`.
- **Docs-only**: "Is live video streaming supported on the Enterprise
  plan, and since which version?" → pulls the doc page + release note.
- **Combined**: fuses both graphs via the shared `Feature` node.
- **Contradiction**: `graph_engine.detect_structural_contradictions` finds
  Feature nodes with an *open* `FeatureRequest` (`requested_by`) **and** a
  `ReleaseNote` that already ships it (`ships_feature`) — e.g. live video
  streaming and role-based dashboards are both flagged this way against
  the fixture release notes.
- **Analytics**: `/api/analytics` returns most-requested features, issue
  counts by tier (enterprise 388 / starter 337 / zero 236 in the real
  dataset), and ARR impact per feature — all computed by graph traversal,
  not hardcoded.

## Known gaps / next steps if you keep building this

- `docs_crawler` should run against the real `llms.txt` manifests once
  network access allows it — the fixture data is only a stand-in.
- `canonicalize_feature()` in `config.py` is a keyword/substring matcher;
  it works for the demo but would benefit from an embedding-based match
  for messier real doc titles.
- The graph explorer sends the full subgraph to the browser on every
  query; fine at this dataset size (~2.5k nodes), would want pagination
  or server-side layout at real scale.
- No auth on the API — add before exposing outside a trusted network.
