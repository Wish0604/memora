"""
schemas.py
Strict Pydantic schemas and dataclasses for Knowledge Mutation Pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime


class MutationOpType(str, Enum):
    CREATE_ACCOUNT = "CREATE_ACCOUNT"
    UPDATE_ACCOUNT = "UPDATE_ACCOUNT"
    CREATE_ISSUE = "CREATE_ISSUE"
    UPDATE_ISSUE = "UPDATE_ISSUE"
    CREATE_FEATURE_REQUEST = "CREATE_FEATURE_REQUEST"
    CREATE_FEATURE = "CREATE_FEATURE"
    CREATE_TASK = "CREATE_TASK"
    CREATE_MEETING_NOTE = "CREATE_MEETING_NOTE"
    CREATE_RELATIONSHIP = "CREATE_RELATIONSHIP"
    UPDATE_RELATIONSHIP = "UPDATE_RELATIONSHIP"


ALLOWED_NODE_TYPES = {
    "Account", "Person", "Issue", "Feature", "FeatureRequest",
    "Task", "MeetingNote", "Plan", "DocPage", "ReleaseNote", "Version"
}

ALLOWED_REL_TYPES = {
    "HAS_ISSUE", "REQUESTED_FEATURE", "ABOUT_FEATURE", "ON_PLAN",
    "RELATED_TO_FEATURE", "MENTIONS_ACCOUNT", "DESCRIBES_FEATURE",
    "SHIPS_FEATURE", "DOCUMENTS_PLAN", "SUPPORTED_ON_PLAN", "HAS_TASK",
    "DERIVED_FROM"
}


@dataclass
class ProvenanceInfo:
    source_type: str = "conversation"  # conversation | api | sync
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    confidence: float = 0.95
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    valid_from: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    valid_to: Optional[str] = None


@dataclass
class MutationOp:
    op_type: MutationOpType
    entity_type: str  # Account | Issue | FeatureRequest | etc.
    target_id: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Optional[ProvenanceInfo] = None


@dataclass
class MutationResult:
    status: str  # committed | rejected | failed
    graph_version: int
    created_nodes: List[str] = field(default_factory=list)
    updated_nodes: List[str] = field(default_factory=list)
    created_edges: List[str] = field(default_factory=list)
    updated_edges: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    message: str = ""
