"""
mutation_service.py
Knowledge Mutation Service:
Executes validated, transactional mutations on the persistent Knowledge Graph
(NetworkX + SQLite and native Neo4j store), attaches provenance metadata,
and fires change events to trigger vector re-indexing and UI refresh.
"""
from __future__ import annotations
import time
from typing import List, Optional, Dict, Any
from datetime import datetime

from .schemas import MutationOp, MutationOpType, MutationResult, ProvenanceInfo
from .resolver import EntityResolver
from .validator import MutationValidator


class MutationService:
    def __init__(self, graph_engine, event_bus=None, retriever=None):
        self.engine = graph_engine
        self.resolver = EntityResolver(graph_engine)
        self.validator = MutationValidator()
        self.event_bus = event_bus
        self.retriever = retriever
        self.version = 1

    def execute_operations(self, ops: List[MutationOp]) -> MutationResult:
        if not ops:
            return MutationResult(status="committed", graph_version=self.version, message="No operations provided")

        created_nodes: List[str] = []
        updated_nodes: List[str] = []
        created_edges: List[str] = []
        updated_edges: List[str] = []
        errors: List[str] = []

        for op in ops:
            # 1. Validate
            is_valid, val_errors = self.validator.validate(op)
            if not is_valid:
                errors.extend(val_errors)
                continue

            # 2. Extract provenance
            prov = op.provenance or ProvenanceInfo()
            now_iso = datetime.utcnow().isoformat()

            # 3. Handle CREATE_ISSUE
            if op.op_type == MutationOpType.CREATE_ISSUE:
                title = op.properties.get("title", "Untitled Issue")
                acc_name = op.properties.get("account_name")
                
                # Resolve account
                acc_id = self.resolver.resolve_account(acc_name) if acc_name else None
                
                # Generate new issue ID
                ts = int(time.time() * 1000) % 1000000
                issue_id = f"issue:iss_usr_{ts}"

                issue_props = {
                    "title": title,
                    "status": op.properties.get("status", "open"),
                    "severity": op.properties.get("severity", "medium"),
                    "source_type": prov.source_type,
                    "conversation_id": prov.conversation_id,
                    "message_id": prov.message_id,
                    "created_at": prov.created_at,
                    "valid_from": prov.valid_from,
                }

                # Add issue node
                self.engine.add_node(issue_id, label=title, node_type="Issue", subgraph="customer", properties=issue_props)
                created_nodes.append(issue_id)

                # Connect account -> HAS_ISSUE -> issue
                if acc_id:
                    self.engine.add_edge(acc_id, issue_id, rel_type="HAS_ISSUE", properties={"created_at": now_iso})
                    created_edges.append(f"{acc_id}->HAS_ISSUE->{issue_id}")

            # 4. Handle UPDATE_ACCOUNT (e.g. plan change)
            elif op.op_type == MutationOpType.UPDATE_ACCOUNT:
                acc_name = op.properties.get("name")
                acc_id = self.resolver.resolve_account(acc_name)
                
                if not acc_id:
                    errors.append(f"Account '{acc_name}' not found for update")
                    continue

                new_tier = op.properties.get("tier")
                if new_tier:
                    # Update account properties
                    if acc_id in self.engine.g:
                        self.engine.g.nodes[acc_id]["properties"]["tier"] = new_tier
                        self.engine.g.nodes[acc_id]["properties"]["updated_at"] = now_iso
                        updated_nodes.append(acc_id)

                    # Update ON_PLAN relationship with temporal validity
                    plan_node_id = f"plan:{new_tier.lower()}"
                    if not self.engine.has_node(plan_node_id):
                        self.engine.add_node(plan_node_id, label=f"{new_tier} Plan", node_type="Plan", subgraph="docs", properties={"tier": new_tier})
                        created_nodes.append(plan_node_id)

                    self.engine.add_edge(acc_id, plan_node_id, rel_type="ON_PLAN", properties={
                        "valid_from": now_iso,
                        "updated_by": prov.source_type
                    })
                    created_edges.append(f"{acc_id}->ON_PLAN->{plan_node_id}")

            # 5. Handle CREATE_FEATURE_REQUEST
            elif op.op_type == MutationOpType.CREATE_FEATURE_REQUEST:
                title = op.properties.get("title", "Untitled Feature Request")
                acc_name = op.properties.get("account_name")
                acc_id = self.resolver.resolve_account(acc_name) if acc_name else None

                ts = int(time.time() * 1000) % 1000000
                fr_id = f"fr:fr_usr_{ts}"

                fr_props = {
                    "title": title,
                    "status": op.properties.get("status", "open"),
                    "source_type": prov.source_type,
                    "conversation_id": prov.conversation_id,
                    "created_at": prov.created_at,
                }

                self.engine.add_node(fr_id, label=title, node_type="FeatureRequest", subgraph="customer", properties=fr_props)
                created_nodes.append(fr_id)

                if acc_id:
                    self.engine.add_edge(acc_id, fr_id, rel_type="REQUESTED_FEATURE", properties={"created_at": now_iso})
                    created_edges.append(f"{acc_id}->REQUESTED_FEATURE->{fr_id}")

        # 6. Commit to persistence
        if created_nodes or updated_nodes or created_edges or updated_edges:
            self.engine.persist()
            self.version += 1

            # 7. Incremental Vector Re-index
            if self.retriever and hasattr(self.retriever, "update_incremental"):
                mutated_ids = created_nodes + updated_nodes
                self.retriever.update_incremental(mutated_ids)

            # 8. Fire Change Event via EventBus
            if self.event_bus:
                self.event_bus.publish({
                    "event": "KNOWLEDGE_GRAPH_UPDATED",
                    "graph_version": self.version,
                    "created_nodes": created_nodes,
                    "updated_nodes": updated_nodes,
                    "created_edges": created_edges,
                    "updated_edges": updated_edges,
                    "timestamp": now_iso,
                })

            status = "committed"
            msg = f"Successfully committed {len(created_nodes)} nodes and {len(created_edges)} edges to Knowledge Graph."
        else:
            status = "failed" if errors else "committed"
            msg = "No graph state changes applied."

        return MutationResult(
            status=status,
            graph_version=self.version,
            created_nodes=created_nodes,
            updated_nodes=updated_nodes,
            created_edges=created_edges,
            updated_edges=updated_edges,
            errors=errors,
            message=msg
        )
