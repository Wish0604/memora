"""
graph_engine.py
Dual Graph Database Engine:
1. Native Neo4j Engine: Connects to Neo4j via official `neo4j` driver, executing parameterized
   Cypher MERGE/MATCH statements for node creation, traversals, and contradiction detection.
2. Embedded Engine: NetworkX + SQLite fallback when Neo4j is not connected.
"""
from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass, asdict

from datetime import datetime
from typing import Any, Iterable, Dict, List, Optional

import networkx as nx

try:
    from neo4j import GraphDatabase, Driver
    HAS_NEO4J_DRIVER = True
except ImportError:
    HAS_NEO4J_DRIVER = False

from config import DB_PATH, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE
from customer_ingest import IngestResult, Account, Issue, FeatureRequest, Task, MeetingNote


# ---------------------------------------------------------------------------
# Native Neo4j Engine Implementation
# ---------------------------------------------------------------------------
class Neo4jGraphEngine:
    def __init__(self, uri: str = NEO4J_URI, user: str = NEO4J_USER, password: str = NEO4J_PASSWORD):
        self.uri = uri
        self.user = user
        self.password = password
        self.driver: Optional[Driver] = None
        self.is_connected = False
        self._connect()

    def _connect(self):
        if not HAS_NEO4J_DRIVER:
            self.is_connected = False
            return

        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            self.is_connected = True
            print(f"[Neo4jGraphEngine] Successfully connected to Neo4j at {self.uri}")
            self._create_constraints()
        except Exception as e:
            print(f"[Neo4jGraphEngine] Neo4j connection failed ({e}). Engine will use fallback.")
            self.is_connected = False

    def close(self):
        if self.driver:
            self.driver.close()

    def _create_constraints(self):
        if not self.is_connected or not self.driver:
            return
        
        constraints = [
            "CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT issue_id IF NOT EXISTS FOR (i:Issue) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT fr_id IF NOT EXISTS FOR (fr:FeatureRequest) REQUIRE fr.id IS UNIQUE",
            "CREATE CONSTRAINT task_id IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE",
            "CREATE CONSTRAINT note_id IF NOT EXISTS FOR (m:MeetingNote) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT feature_id IF NOT EXISTS FOR (f:Feature) REQUIRE f.id IS UNIQUE",
            "CREATE CONSTRAINT doc_url IF NOT EXISTS FOR (d:DocPage) REQUIRE d.url IS UNIQUE",
            "CREATE CONSTRAINT release_url IF NOT EXISTS FOR (r:ReleaseNote) REQUIRE r.url IS UNIQUE",
        ]
        
        with self.driver.session(database=NEO4J_DATABASE) as session:
            for c in constraints:
                try:
                    session.run(c)
                except Exception:
                    pass

    def build_customer_graph(self, data: IngestResult):
        if not self.is_connected or not self.driver:
            return

        with self.driver.session(database=NEO4J_DATABASE) as session:
            # 1. Accounts & Plans
            for acc in data.accounts.values():
                session.run(
                    """
                    MERGE (a:Account {id: $id})
                    SET a.name = $name, a.industry = $industry, a.region = $region,
                        a.tier = $tier, a.health = $health, a.arr = $arr, a.owner = $owner
                    MERGE (p:Plan {name: $tier_name})
                    MERGE (a)-[:ON_PLAN]->(p)
                    """,
                    id=acc.id, name=acc.name, industry=acc.industry, region=acc.region,
                    tier=acc.tier, health=acc.health, arr=acc.arr, owner=acc.owner,
                    tier_name=acc.tier.capitalize()
                )

            # 2. Issues & Features
            for iss in data.issues:
                session.run(
                    """
                    MERGE (i:Issue {id: $id})
                    SET i.title = $title, i.category = $category, i.status = $status
                    WITH i
                    MATCH (a:Account {name: $account_name})
                    MERGE (a)-[:HAS_ISSUE]->(i)
                    """,
                    id=iss.id, title=iss.title, category=iss.category, status=iss.status,
                    account_name=iss.account_name
                )

            # 3. Feature Requests
            for fr in data.feature_requests:
                session.run(
                    """
                    MERGE (fr:FeatureRequest {id: $id})
                    SET fr.title = $title, fr.product_area = $product_area,
                        fr.status = $status, fr.revenue_impact = $revenue_impact
                    """,
                    id=fr.id, title=fr.title, product_area=fr.product_area,
                    status=fr.status, revenue_impact=fr.revenue_impact
                )
                if fr.canonical_feature:
                    session.run(
                        """
                        MERGE (f:Feature {id: $feat_id})
                        SET f.name = $feat_id
                        WITH f
                        MATCH (fr:FeatureRequest {id: $fr_id})
                        MERGE (fr)-[:ABOUT_FEATURE]->(f)
                        """,
                        feat_id=fr.canonical_feature, fr_id=fr.id
                    )
                for acc_name in fr.accounts:
                    session.run(
                        """
                        MATCH (a:Account {name: $acc_name}), (fr:FeatureRequest {id: $fr_id})
                        MERGE (a)-[:REQUESTED_FEATURE]->(fr)
                        """,
                        acc_name=acc_name, fr_id=fr.id
                    )

            # 4. Tasks
            for t in data.tasks:
                session.run(
                    """
                    MERGE (t:Task {id: $id})
                    SET t.title = $title, t.assignee = $assignee, t.priority = $priority,
                        t.status = $status, t.due = $due
                    WITH t
                    MATCH (a:Account {name: $acc_name})
                    MERGE (a)-[:HAS_TASK]->(t)
                    """,
                    id=t.id, title=t.title, assignee=t.assignee, priority=t.priority,
                    status=t.status, due=t.due, acc_name=t.account_name
                )

            # 5. Meeting Notes
            for mn in data.meeting_notes:
                session.run(
                    """
                    MERGE (m:MeetingNote {id: $id})
                    SET m.topic = $topic, m.date = $date, m.action_items = $action_items
                    WITH m
                    MATCH (a:Account {name: $acc_name})
                    MERGE (m)-[:MENTIONS_ACCOUNT]->(a)
                    """,
                    id=mn.id, topic=mn.topic, date=mn.date, action_items=json.dumps(mn.action_items),
                    acc_name=mn.account_name
                )

    def build_docs_graph(self, pages: list):
        if not self.is_connected or not self.driver:
            return

        with self.driver.session(database=NEO4J_DATABASE) as session:
            for p in pages:
                if getattr(p, 'source', '') == 'releases':
                    session.run(
                        """
                        MERGE (r:ReleaseNote {url: $url})
                        SET r.title = $title, r.content = $content, r.last_fetched = $last_fetched
                        """,
                        url=p.url, title=p.title, content=p.content[:1000], last_fetched=p.last_fetched_at
                    )
                    for feat in getattr(p, 'canonical_features', []):
                        session.run(
                            """
                            MERGE (f:Feature {id: $feat_id})
                            SET f.name = $feat_id
                            WITH f
                            MATCH (r:ReleaseNote {url: $url})
                            MERGE (r)-[:SHIPS_FEATURE]->(f)
                            """,
                            feat_id=feat, url=p.url
                        )
                else:
                    session.run(
                        """
                        MERGE (d:DocPage {url: $url})
                        SET d.title = $title, d.content = $content, d.last_fetched = $last_fetched
                        """,
                        url=p.url, title=p.title, content=p.content[:1000], last_fetched=p.last_fetched_at
                    )
                    for feat in getattr(p, 'canonical_features', []):
                        session.run(
                            """
                            MERGE (f:Feature {id: $feat_id})
                            SET f.name = $feat_id
                            WITH f
                            MATCH (d:DocPage {url: $url})
                            MERGE (d)-[:DESCRIBES_FEATURE]->(f)
                            """,
                            feat_id=feat, url=p.url
                        )

    def nodes_by_type(self, node_type: str) -> list[Node]:
        if not self.is_connected or not self.driver:
            return []
        with self.driver.session(database=NEO4J_DATABASE) as session:
            try:
                res = session.run(f"MATCH (n:{node_type}) RETURN n.id AS id, properties(n) AS props")
                nodes = []
                for r in res:
                    props = dict(r["props"])
                    nid = r["id"] or props.get("url") or str(props)
                    label = props.get("name") or props.get("title") or nid
                    nodes.append(Node(
                        id=nid,
                        type=node_type,
                        label=label,
                        subgraph="neo4j",
                        properties=props
                    ))
                return nodes
            except Exception:
                return []


    def detect_contradictions(self) -> list[dict]:

        if not self.is_connected or not self.driver:
            return []
        with self.driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(
                """
                MATCH (fr:FeatureRequest)-[:ABOUT_FEATURE]->(f:Feature)<-[:SHIPS_FEATURE]-(rel:ReleaseNote)
                WHERE fr.status IN ['new', 'in_progress']
                RETURN fr.id AS request_id, fr.title AS fr_title, fr.status AS fr_status,
                       rel.title AS rel_title, rel.url AS rel_url
                """
            )
            contradictions = []
            for record in result:
                contradictions.append({
                    "feature_request_id": record["request_id"],
                    "feature_title": record["fr_title"],
                    "request_status": record["fr_status"],
                    "release_title": record["rel_title"],
                    "release_url": record["rel_url"],
                    "description": f"Customer request '{record['fr_title']}' is marked '{record['fr_status']}', but release note '{record['rel_title']}' indicates it has already shipped."
                })
            return contradictions


    def get_stats(self) -> dict:
        if not self.is_connected or not self.driver:
            return {"total_nodes": 0, "total_edges": 0}
        with self.driver.session(database=NEO4J_DATABASE) as session:
            n_res = session.run("MATCH (n) RETURN count(n) AS node_count")
            node_count = n_res.single()["node_count"]
            e_res = session.run("MATCH ()-[r]->() RETURN count(r) AS edge_count")
            edge_count = e_res.single()["edge_count"]
            return {"total_nodes": node_count, "total_edges": edge_count, "engine": "Neo4j Cypher"}


# ---------------------------------------------------------------------------
# Embedded NetworkX + SQLite Engine Implementation
# ---------------------------------------------------------------------------
@dataclass
class Node:
    id: str
    type: str
    label: str
    properties: dict[str, Any]
    subgraph: str


@dataclass
class Edge:
    src: str
    dst: str
    type: str
    properties: dict[str, Any]


class GraphEngine:
    """Dual-graph store: one nx.MultiDiGraph in memory, mirrored to SQLite."""

    def __init__(self, db_path=DB_PATH, reset: bool = False):
        self.db_path = str(db_path)
        self.g = nx.MultiDiGraph()
        self._init_db(reset=reset)

    def _init_db(self, reset: bool = False):
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cur = self._conn.cursor()
        if reset:
            cur.executescript("DROP TABLE IF EXISTS nodes; DROP TABLE IF EXISTS edges;")
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY, type TEXT, label TEXT, subgraph TEXT, properties TEXT
            );
            CREATE TABLE IF NOT EXISTS edges (
                src TEXT, dst TEXT, type TEXT, properties TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
            CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
            """
        )
        self._conn.commit()

    def persist(self):
        cur = self._conn.cursor()
        cur.execute("DELETE FROM nodes")
        cur.execute("DELETE FROM edges")
        for nid, data in self.g.nodes(data=True):
            cur.execute(
                "INSERT INTO nodes VALUES (?,?,?,?,?)",
                (nid, data.get("type"), data.get("label"), data.get("subgraph"), json.dumps(data.get("properties", {}))),
            )
        for u, v, data in self.g.edges(data=True):
            cur.execute(
                "INSERT INTO edges VALUES (?,?,?,?)",
                (u, v, data.get("type"), json.dumps(data.get("properties", {}))),
            )
        self._conn.commit()

    def add_node(self, node: Node):
        self.g.add_node(
            node.id,
            type=node.type,
            label=node.label,
            subgraph=node.subgraph,
            properties=node.properties,
        )

    def add_edge(self, edge: Edge):
        self.g.add_edge(edge.src, edge.dst, type=edge.type, properties=edge.properties)

    def nodes_by_type(self, node_type: str) -> list[Node]:
        results = []
        for n, data in self.g.nodes(data=True):
            if data.get("type") == node_type:
                results.append(Node(
                    id=n,
                    type=data.get("type", node_type),
                    label=data.get("label", n),
                    subgraph=data.get("subgraph", "customer"),
                    properties=data.get("properties", {})
                ))
        return results

    def get_node(self, node_id: str) -> Node | None:
        if node_id not in self.g:
            return None
        data = self.g.nodes[node_id]
        return Node(
            id=node_id,
            type=data.get("type", ""),
            label=data.get("label", node_id),
            subgraph=data.get("subgraph", "customer"),
            properties=data.get("properties", {})
        )

    def multi_hop(self, seed_ids: list[str], hops: int = 1) -> set[str]:
        visited = set()
        for s in seed_ids:
            visited.update(self.get_neighbors(s, radius=hops))
        return visited

    def get_neighbors(self, node_id: str, radius: int = 1) -> list[str]:

        if node_id not in self.g:
            return []
        visited = set([node_id])
        current_layer = set([node_id])
        for _ in range(radius):
            next_layer = set()
            for n in current_layer:
                nbrs = set(self.g.successors(n)).union(set(self.g.predecessors(n)))
                next_layer.update(nbrs - visited)
            visited.update(next_layer)
            current_layer = next_layer
        return list(visited)

    def subgraph(self, node_ids: list[str]) -> dict:
        valid_ids = set(nid for nid in node_ids if nid in self.g)
        nodes_out = []
        for nid in valid_ids:
            data = self.g.nodes[nid]
            nodes_out.append({
                "id": nid,
                "label": data.get("label", nid),
                "type": data.get("type", "Node"),
                "subgraph": data.get("subgraph", "customer"),
                "properties": data.get("properties", {}),
            })
        edges_out = []
        seen_edges = set()
        for u in valid_ids:
            for v in self.g.successors(u):
                if v in valid_ids:
                    key = (u, v)
                    if key not in seen_edges:
                        seen_edges.add(key)
                        edge_data = self.g.get_edge_data(u, v)
                        ed_type = "RELATED"
                        if edge_data:
                            first_val = next(iter(edge_data.values()), {})
                            ed_type = first_val.get("type", "RELATED")
                        edges_out.append({
                            "source": u,
                            "target": v,
                            "type": ed_type,
                        })
        return {"nodes": nodes_out, "edges": edges_out}

    def get_full_graph(self, max_nodes: int = 5000) -> dict:
        nodes_out = []
        node_ids_set = set()
        for nid, data in self.g.nodes(data=True):
            node_ids_set.add(nid)
            nodes_out.append({
                "id": str(nid),
                "label": data.get("label", str(nid)),
                "type": data.get("type", "Node"),
                "subgraph": data.get("subgraph", "customer"),
                "properties": data.get("properties", {}),
            })
            if len(nodes_out) >= max_nodes:
                break

        edges_out = []
        seen_edges = set()
        edge_idx = 1
        for u, v, data in self.g.edges(data=True):
            if u in node_ids_set and v in node_ids_set:
                rel_type = data.get("type", "CONNECTED_TO")
                key = (u, v, rel_type)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges_out.append({
                        "id": f"rel_{edge_idx}",
                        "source": str(u),
                        "target": str(v),
                        "type": rel_type,
                        "properties": data.get("properties", {}),
                    })
                    edge_idx += 1

        return {
            "nodes": nodes_out,
            "edges": edges_out,
        }

    def stats(self) -> dict:
        return self.get_stats()

    def get_stats(self) -> dict:

        node_types = {}
        for _, data in self.g.nodes(data=True):
            t = data.get("type", "unknown")
            node_types[t] = node_types.get(t, 0) + 1

        edge_types = {}
        for _, _, data in self.g.edges(data=True):
            t = data.get("type", "unknown")
            edge_types[t] = edge_types.get(t, 0) + 1

        return {
            "total_nodes": self.g.number_of_nodes(),
            "total_edges": self.g.number_of_edges(),
            "node_counts": node_types,
            "edge_counts": edge_types,
            "engine": "Embedded NetworkX + SQLite"
        }


# ---------------------------------------------------------------------------
# Builder helper functions
# ---------------------------------------------------------------------------
def build_customer_graph(engine: GraphEngine, data: IngestResult):
    for acc in data.accounts.values():
        engine.add_node(Node(id=f"account:{acc.id}", type="Account", label=acc.name, subgraph="customer", properties=asdict(acc)))
        engine.add_node(Node(id=f"plan:{acc.tier}", type="Plan", label=acc.tier.capitalize(), subgraph="shared", properties={"name": acc.tier}))
        engine.add_edge(Edge(src=f"account:{acc.id}", dst=f"plan:{acc.tier}", type="on_plan", properties={}))

    for iss in data.issues:
        engine.add_node(Node(id=f"issue:{iss.id}", type="Issue", label=iss.title, subgraph="customer", properties=asdict(iss)))
        engine.add_edge(Edge(src=f"account:{iss.account_name}", dst=f"issue:{iss.id}", type="has_issue", properties={}))

    for fr in data.feature_requests:
        engine.add_node(Node(id=f"fr:{fr.id}", type="FeatureRequest", label=fr.title, subgraph="customer", properties=asdict(fr)))
        if fr.canonical_feature:
            engine.add_node(Node(id=f"feature:{fr.canonical_feature}", type="Feature", label=fr.canonical_feature, subgraph="shared", properties={"key": fr.canonical_feature}))
            engine.add_edge(Edge(src=f"fr:{fr.id}", dst=f"feature:{fr.canonical_feature}", type="about_feature", properties={}))
        for acc_name in fr.accounts:
            engine.add_edge(Edge(src=f"account:{acc_name}", dst=f"fr:{fr.id}", type="requested_feature", properties={}))

    for t in data.tasks:
        engine.add_node(Node(id=f"task:{t.id}", type="Task", label=t.title, subgraph="customer", properties=asdict(t)))
        engine.add_edge(Edge(src=f"account:{t.account_name}", dst=f"task:{t.id}", type="has_task", properties={}))

    for mn in data.meeting_notes:
        engine.add_node(Node(id=f"note:{mn.id}", type="MeetingNote", label=mn.topic, subgraph="customer", properties=asdict(mn)))
        engine.add_edge(Edge(src=f"note:{mn.id}", dst=f"account:{mn.account_name}", type="mentions_account", properties={}))


def build_docs_graph(engine: GraphEngine, pages: list):
    for p in pages:
        ntype = "ReleaseNote" if getattr(p, 'source', '') == "releases" else "DocPage"
        engine.add_node(Node(id=f"doc:{p.url}", type=ntype, label=p.title, subgraph="docs", properties={"url": p.url, "title": p.title, "content": p.content[:500]}))
        for feat_key in getattr(p, 'canonical_features', []):
            engine.add_node(Node(id=f"feature:{feat_key}", type="Feature", label=feat_key, subgraph="shared", properties={"key": feat_key}))
            rel_type = "ships_feature" if ntype == "ReleaseNote" else "describes_feature"
            engine.add_edge(Edge(src=f"doc:{p.url}", dst=f"feature:{feat_key}", type=rel_type, properties={}))
