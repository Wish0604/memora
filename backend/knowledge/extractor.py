"""
extractor.py
Knowledge Extractor:
Parses user chat interactions to extract candidate structured fact mutations
(e.g., creating issues, updating account plans, adding feature requests).
"""
from __future__ import annotations
import re
from typing import List, Optional, Dict, Any
from .schemas import MutationOp, MutationOpType, ProvenanceInfo


class KnowledgeExtractor:
    # Pattern triggers for chat knowledge extraction
    ISSUE_PATTERNS = [
        r"(?P<account>[A-Z][A-Za-z0-9\s]+?)\s+(?:has reported|reported|has|encountered)\s+(?:an?|a new)?\s*(?:urgent|critical|open)?\s*issue(?:\s+with|\s+about)?\s+[\"']?(?P<title>[^.\n\"']+)[\"']?",
        r"(?:add|create)\s+(?:an?|a new)?\s*issue\s+for\s+(?P<account>[A-Z][A-Za-z0-9\s]+?):\s*[\"']?(?P<title>[^.\n\"']+)[\"']?",
        r"(?P<account>[A-Z][A-Za-z0-9\s]+?)\s+reported\s+that\s+(?P<title>[^.\n]+)",
    ]

    PLAN_PATTERNS = [
        r"(?P<account>[A-Z][A-Za-z0-9\s]+?)\s+(?:is now on|moved to|upgraded to|changed to)\s+(?:the\s+)?(?P<tier>enterprise|pro|starter|custom|free)\s+plan",
        r"(?:update|set)\s+(?P<account>[A-Z][A-Za-z0-9\s]+?)\s+(?:plan|tier)\s+to\s+(?P<tier>enterprise|pro|starter|custom|free)",
    ]

    FEATURE_REQUEST_PATTERNS = [
        r"(?P<account>[A-Z][A-Za-z0-9\s]+?)\s+(?:requested|asked for|needs|wants)\s+(?:a new feature|feature)?\s*[\"']?(?P<title>[^.\n\"']+)[\"']?",
    ]

    def extract(self, text: str, conversation_id: Optional[str] = None, message_id: Optional[str] = None) -> List[MutationOp]:
        ops: List[MutationOp] = []
        clean_text = text.strip()

        prov = ProvenanceInfo(
            source_type="conversation",
            conversation_id=conversation_id,
            message_id=message_id,
            confidence=0.92
        )

        # 1. Issue extraction
        for pat in self.ISSUE_PATTERNS:
            match = re.search(pat, clean_text, re.IGNORECASE)
            if match:
                gd = match.groupdict()
                acc_name = gd.get("account", "").strip()
                title = gd.get("title", "").strip()

                if acc_name and title:
                    ops.append(MutationOp(
                        op_type=MutationOpType.CREATE_ISSUE,
                        entity_type="Issue",
                        properties={
                            "title": title,
                            "status": "open",
                            "severity": "high" if "urgent" in clean_text.lower() or "critical" in clean_text.lower() else "medium",
                            "account_name": acc_name,
                        },
                        relationships=[
                            {"type": "HAS_ISSUE", "from_account": acc_name}
                        ],
                        provenance=prov
                    ))
                    break

        # 2. Plan update extraction
        for pat in self.PLAN_PATTERNS:
            match = re.search(pat, clean_text, re.IGNORECASE)
            if match:
                gd = match.groupdict()
                acc_name = gd.get("account", "").strip()
                tier = gd.get("tier", "").capitalize()

                if acc_name and tier:
                    ops.append(MutationOp(
                        op_type=MutationOpType.UPDATE_ACCOUNT,
                        entity_type="Account",
                        properties={
                            "name": acc_name,
                            "tier": tier,
                        },
                        relationships=[
                            {"type": "ON_PLAN", "to_plan": tier}
                        ],
                        provenance=prov
                    ))
                    break

        # 3. Feature Request extraction
        for pat in self.FEATURE_REQUEST_PATTERNS:
            match = re.search(pat, clean_text, re.IGNORECASE)
            if match and not ops:  # avoid double matching issues
                gd = match.groupdict()
                acc_name = gd.get("account", "").strip()
                title = gd.get("title", "").strip()

                if acc_name and title:
                    ops.append(MutationOp(
                        op_type=MutationOpType.CREATE_FEATURE_REQUEST,
                        entity_type="FeatureRequest",
                        properties={
                            "title": title,
                            "status": "open",
                            "account_name": acc_name,
                        },
                        relationships=[
                            {"type": "REQUESTED_FEATURE", "from_account": acc_name}
                        ],
                        provenance=prov
                    ))
                    break

        return ops
