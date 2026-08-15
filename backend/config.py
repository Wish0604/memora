"""
config.py
Central configuration for the Graph-Based Knowledge-Base Agent.
All paths, endpoints, caching, and model parameters live here so the
rest of the codebase never hardcodes them.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DATA_DIR = (ROOT_DIR / "dataset") if (ROOT_DIR / "dataset").exists() else (BASE_DIR / "data")
CACHE_DIR = BASE_DIR / "cache"
DB_PATH = BASE_DIR / "cache" / "graph.sqlite"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Customer dataset files (as delivered)
# ---------------------------------------------------------------------------
CUSTOMER_FILES = {
    "accounts": DATA_DIR / "accounts.md",
    "issues": DATA_DIR / "issues.md",
    "feature_requests": DATA_DIR / "feature_requests.md",
    "tasks": DATA_DIR / "tasks.md",
    "meeting_notes": DATA_DIR / "meeting_notes.md",
}

# ---------------------------------------------------------------------------
# Live docs / release notes sources
# ---------------------------------------------------------------------------
DOCS_BASE_URL = "https://docs.flytbase.com"
RELEASES_BASE_URL = "https://releases.flytbase.com"
DOCS_LLMS_TXT = f"{DOCS_BASE_URL}/llms.txt"
RELEASES_LLMS_TXT = f"{RELEASES_BASE_URL}/llms.txt"

# How long a cached page is considered fresh before a query-time re-fetch
# is triggered (seconds). Callers can force a re-fetch regardless.
DOC_CACHE_TTL_SECONDS = int(os.environ.get("DOC_CACHE_TTL_SECONDS", 60 * 60 * 6))  # 6h
DOC_FETCH_TIMEOUT_SECONDS = 15
DOC_FETCH_CONCURRENCY = 8
DOC_MAX_PAGES = int(os.environ.get("DOC_MAX_PAGES", 400))  # safety cap on crawl size

# ---------------------------------------------------------------------------
# Retrieval / vector index parameters
# ---------------------------------------------------------------------------
@dataclass
class RetrievalConfig:
    vector_top_k: int = 8
    graph_hop_expansion: int = 1
    min_similarity: float = 0.05
    max_context_chars: int = 12000
    chunk_size_chars: int = 800
    chunk_overlap_chars: int = 120


retrieval_config = RetrievalConfig()

# ---------------------------------------------------------------------------
# Neo4j Graph Database Configuration
# ---------------------------------------------------------------------------
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# ---------------------------------------------------------------------------
# LLM / Reasoner (Google Gemini API)
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")


# ---------------------------------------------------------------------------
# Canonical feature-name normalization
# Maps loose text mentions -> a canonical Feature key, so customer feature
# requests can be linked to doc/release Feature nodes with the same key.
# This is intentionally simple (substring/keyword based) rather than an LLM
# call, so graph linking is deterministic and cheap.
# ---------------------------------------------------------------------------
FEATURE_CANONICAL_MAP: dict[str, list[str]] = {
    "live_video_streaming": ["live video", "live stream", "streaming", "video feed", "live feed"],
    "offline_mission_caching": ["offline mission", "low-connectivity", "offline caching"],
    "scheduled_missions": ["scheduled recurring mission", "recurring mission", "scheduled mission"],
    "custom_alerts": ["custom alert", "alert threshold", "alert quiet hours"],
    "role_based_dashboard": ["role-based dashboard", "custom user roles", "per-role"],
    "fleet_comparison": ["fleet comparison", "cross-account fleet"],
    "push_notifications": ["push notification", "mobile push"],
    "data_retention": ["data retention", "retention window", "retention tier", "cold storage archive"],
    "api_rate_limits": ["api rate limit", "rate limit increase"],
    "firmware_management": ["firmware rollback", "firmware scheduling", "firmware update"],
    "multi_language_ui": ["multi-language", "multi language", "operator interface language"],
    "weather_rescheduling": ["weather-based", "weather rescheduling"],
    "compliance_reports": ["compliance report", "audit log"],
    "mapping_integration": ["mapping layer", "map basemap", "offline map pack"],
    "device_calendar": ["device calendar", "shared calendar"],
    "sso": ["single sign-on", "sso"],
    "two_factor_auth": ["two-factor", "2fa"],
    "webhooks": ["webhook"],
    "geofencing": ["geofence"],
    "detection_zones": ["detection zone", "detection count overlay"],
    "device_transfer": ["device transfer", "cross-organization device"],
    "sandbox_environment": ["sandbox environment", "api sandbox"],
    "siem_export": ["siem", "alert export"],
    "session_timeout": ["session timeout"],
    "split_screen_view": ["split-screen", "split screen"],
    "bulk_operations": ["bulk export", "bulk import", "bulk device", "bulk re-assignment", "bulk tagging", "batch renaming"],
}


def canonicalize_feature(text: str) -> str | None:
    """Best-effort mapping of free text to a canonical feature key."""
    t = text.lower()
    for key, keywords in FEATURE_CANONICAL_MAP.items():
        for kw in keywords:
            if kw in t:
                return key
    return None
