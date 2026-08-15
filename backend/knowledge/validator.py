"""
validator.py
Mutation Validator:
Enforces strict schema constraints, allowed node/relationship types,
and input sanity to prevent ontology corruption or code injection.
"""
from __future__ import annotations
from typing import Tuple, List
from .schemas import MutationOp, ALLOWED_NODE_TYPES, ALLOWED_REL_TYPES, MutationOpType


class MutationValidator:
    def validate(self, op: MutationOp) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        if not isinstance(op.op_type, MutationOpType):
            errors.append(f"Invalid operation type: {op.op_type}")

        if op.entity_type not in ALLOWED_NODE_TYPES:
            errors.append(f"Disallowed entity type '{op.entity_type}'. Must be one of {ALLOWED_NODE_TYPES}")

        # Check relationships
        for rel in op.relationships:
            rel_type = rel.get("type", "")
            if rel_type and rel_type not in ALLOWED_REL_TYPES:
                errors.append(f"Disallowed relationship type '{rel_type}'. Must be one of {ALLOWED_REL_TYPES}")

        # Operation specific requirements
        if op.op_type in (MutationOpType.CREATE_ISSUE, MutationOpType.UPDATE_ISSUE):
            title = op.properties.get("title") or op.properties.get("label")
            if not title and not op.target_id:
                errors.append("Issue creation/update requires a title or target_id")

        if op.op_type in (MutationOpType.CREATE_ACCOUNT, MutationOpType.UPDATE_ACCOUNT):
            name = op.properties.get("name") or op.properties.get("label")
            if not name and not op.target_id:
                errors.append("Account creation/update requires an account name or target_id")

        return (len(errors) == 0, errors)
