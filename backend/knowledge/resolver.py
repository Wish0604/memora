"""
resolver.py
Entity Resolution Service:
Resolves mentions in user interactions (e.g. "Acme", "Acme Robotics", "live video streaming")
to authoritative node IDs in the Knowledge Graph store.
"""
from __future__ import annotations
import re
from typing import Optional, Dict, Any, List, Tuple
from difflib import SequenceMatcher


class EntityResolver:
    def __init__(self, graph_engine):
        self.engine = graph_engine

    def _normalize(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"\b(inc|corp|corporation|ltd|limited|llc|co)\b", "", text)
        return re.sub(r"[^\w\s]", "", text).strip()

    def resolve_account(self, name_or_id: str) -> Optional[str]:
        if not name_or_id:
            return None
        
        # 1. Exact ID match
        canonical_id = name_or_id if name_or_id.startswith("account:") else f"account:{name_or_id.lower().replace(' ', '_')}"
        if canonical_id in self.engine.g:
            return canonical_id

        norm_query = self._normalize(name_or_id)
        
        # 2. Iterate account nodes
        best_id = None
        best_score = 0.0

        for nid, data in self.engine.g.nodes(data=True):
            if data.get("type") != "Account":
                continue
            
            label = data.get("label", "")
            node_name = data.get("properties", {}).get("name", label)
            norm_node = self._normalize(node_name)

            if norm_query == norm_node:
                return nid
            
            # Substring match
            if norm_query in norm_node or norm_node in norm_query:
                score = 0.85
            else:
                score = SequenceMatcher(None, norm_query, norm_node).ratio()

            if score > best_score and score >= 0.70:
                best_score = score
                best_id = nid

        return best_id

    def resolve_feature(self, feature_name: str) -> Optional[str]:
        if not feature_name:
            return None

        canonical_key = feature_name.lower().replace(" ", "_")
        canonical_id = f"feature:{canonical_key}"
        if canonical_id in self.engine.g:
            return canonical_id

        norm_query = self._normalize(feature_name)
        best_id = None
        best_score = 0.0

        for nid, data in self.engine.g.nodes(data=True):
            if data.get("type") not in ("Feature", "FeatureRequest"):
                continue
            
            label = data.get("label", "")
            norm_node = self._normalize(label)

            if norm_query == norm_node:
                return nid

            score = SequenceMatcher(None, norm_query, norm_node).ratio()
            if score > best_score and score >= 0.65:
                best_score = score
                best_id = nid

        return best_id

    def resolve_issue(self, title_or_id: str) -> Optional[str]:
        if not title_or_id:
            return None

        canonical_id = title_or_id if title_or_id.startswith("issue:") else f"issue:{title_or_id.lower().replace(' ', '_')}"
        if canonical_id in self.engine.g:
            return canonical_id

        norm_query = self._normalize(title_or_id)
        for nid, data in self.engine.g.nodes(data=True):
            if data.get("type") == "Issue":
                label = data.get("label", "")
                if self._normalize(label) == norm_query:
                    return nid
        return None
