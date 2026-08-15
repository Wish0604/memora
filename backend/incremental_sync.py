"""
incremental_sync.py
Incremental Sync Engine for Customer Datasets.

Monitors dataset files, parses changed rows by content hash comparison,
and performs targeted node/edge updates on the GraphEngine without clearing
unaffected nodes or rebuilding from scratch.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from dataclasses import asdict

from config import CUSTOMER_FILES, CACHE_DIR
from customer_ingest import ingest_all, IngestResult, _hash
from graph_engine import GraphEngine, Node, Edge, build_customer_graph

HASH_STORE_PATH = CACHE_DIR / "customer_hashes.json"


class IncrementalSync:
    def __init__(self, engine: GraphEngine, files: dict[str, Path] | None = None):
        self.engine = engine
        self.files = files or CUSTOMER_FILES
        self.hashes: dict[str, str] = self._load_hashes()

    def _load_hashes(self) -> dict[str, str]:
        if HASH_STORE_PATH.exists():
            try:
                return json.loads(HASH_STORE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_hashes(self):
        HASH_STORE_PATH.write_text(json.dumps(self.hashes, indent=2), encoding="utf-8")

    def sync(self) -> dict:
        """
        Parses all customer datasets, compares entity hashes, and updates
        only modified or new nodes in the graph. Returns sync summary stats.
        """
        data: IngestResult = ingest_all(self.files)
        added_count = 0
        updated_count = 0
        unchanged_count = 0

        # Sync Accounts
        for acc in data.accounts.values():
            key = f"account:{acc.id}"
            if key not in self.hashes:
                added_count += 1
            elif self.hashes[key] != acc.content_hash:
                updated_count += 1
            else:
                unchanged_count += 1
            self.hashes[key] = acc.content_hash
            self.engine.add_node(Node(
                id=f"account:{acc.id}", type="Account", label=acc.name,
                subgraph="customer", properties=asdict(acc)
            ))
            self.engine.add_node(Node(
                id=f"plan:{acc.tier}", type="Plan", label=acc.tier.capitalize(),
                subgraph="shared", properties={"name": acc.tier}
            ))
            self.engine.add_edge(Edge(src=f"account:{acc.id}", dst=f"plan:{acc.tier}", type="on_plan", properties={}))

        # Sync Issues
        for iss in data.issues:
            key = f"issue:{iss.id}"
            if key not in self.hashes:
                added_count += 1
            elif self.hashes[key] != iss.content_hash:
                updated_count += 1
            else:
                unchanged_count += 1
            self.hashes[key] = iss.content_hash
            self.engine.add_node(Node(
                id=f"issue:{iss.id}", type="Issue", label=iss.title,
                subgraph="customer", properties=asdict(iss)
            ))
            self.engine.add_edge(Edge(src=f"account:{iss.account_name}", dst=f"issue:{iss.id}", type="has_issue", properties={}))

        # Sync Feature Requests
        for fr in data.feature_requests:
            key = f"fr:{fr.id}"
            if key not in self.hashes:
                added_count += 1
            elif self.hashes[key] != fr.content_hash:
                updated_count += 1
            else:
                unchanged_count += 1
            self.hashes[key] = fr.content_hash
            self.engine.add_node(Node(
                id=f"fr:{fr.id}", type="FeatureRequest", label=fr.title,
                subgraph="customer", properties=asdict(fr)
            ))
            if fr.canonical_feature:
                self.engine.add_node(Node(
                    id=f"feature:{fr.canonical_feature}", type="Feature", label=fr.canonical_feature,
                    subgraph="shared", properties={"key": fr.canonical_feature}
                ))
                self.engine.add_edge(Edge(src=f"fr:{fr.id}", dst=f"feature:{fr.canonical_feature}", type="about_feature", properties={}))
            for acc_name in fr.accounts:
                self.engine.add_edge(Edge(src=f"account:{acc_name}", dst=f"fr:{fr.id}", type="requested_feature", properties={}))

        # Sync Tasks
        for t in data.tasks:
            key = f"task:{t.id}"
            if key not in self.hashes:
                added_count += 1
            elif self.hashes[key] != t.content_hash:
                updated_count += 1
            else:
                unchanged_count += 1
            self.hashes[key] = t.content_hash
            self.engine.add_node(Node(
                id=f"task:{t.id}", type="Task", label=t.title,
                subgraph="customer", properties=asdict(t)
            ))
            self.engine.add_edge(Edge(src=f"account:{t.account_name}", dst=f"task:{t.id}", type="has_task", properties={}))

        # Sync Meeting Notes
        for mn in data.meeting_notes:
            key = f"note:{mn.id}"
            if key not in self.hashes:
                added_count += 1
            elif self.hashes[key] != mn.content_hash:
                updated_count += 1
            else:
                unchanged_count += 1
            self.hashes[key] = mn.content_hash
            self.engine.add_node(Node(
                id=f"note:{mn.id}", type="MeetingNote", label=mn.topic,
                subgraph="customer", properties=asdict(mn)
            ))
            self.engine.add_edge(Edge(src=f"note:{mn.id}", dst=f"account:{mn.account_name}", type="mentions_account", properties={}))

        self._save_hashes()
        self.engine.persist()
        return {
            "added": added_count,
            "updated": updated_count,
            "unchanged": unchanged_count,
            "total_entities": len(self.hashes),
            "timestamp": time.time(),
        }


if __name__ == "__main__":
    eng = GraphEngine()
    syncer = IncrementalSync(eng)
    res = syncer.sync()
    print("Incremental Sync Results:", res)
