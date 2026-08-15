"""
usage_signals.py
Lightweight query logging + usage telemetry, backed by the same SQLite
file used by the graph engine (separate table). Powers /api/analytics.
"""
from __future__ import annotations
import sqlite3
import time
from dataclasses import dataclass

from config import DB_PATH


@dataclass
class QueryLogEntry:
    query: str
    intent: str
    latency_ms: float
    citation_count: int
    contradiction_count: int
    timestamp: float


class UsageSignals:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT,
                intent TEXT,
                latency_ms REAL,
                citation_count INTEGER,
                contradiction_count INTEGER,
                timestamp REAL
            )
            """
        )
        self.conn.commit()

    def log(self, entry: QueryLogEntry):
        self.conn.execute(
            "INSERT INTO query_log (query, intent, latency_ms, citation_count, contradiction_count, timestamp) VALUES (?,?,?,?,?,?)",
            (entry.query, entry.intent, entry.latency_ms, entry.citation_count, entry.contradiction_count, entry.timestamp),
        )
        self.conn.commit()

    def summary(self) -> dict:
        cur = self.conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM query_log").fetchone()[0]
        by_intent = dict(cur.execute("SELECT intent, COUNT(*) FROM query_log GROUP BY intent").fetchall())
        avg_latency = cur.execute("SELECT AVG(latency_ms) FROM query_log").fetchone()[0] or 0
        recent = cur.execute(
            "SELECT query, intent, latency_ms, citation_count, timestamp FROM query_log ORDER BY id DESC LIMIT 20"
        ).fetchall()
        return {
            "total_queries": total,
            "by_intent": by_intent,
            "avg_latency_ms": round(avg_latency, 1),
            "recent_queries": [
                {"query": q, "intent": i, "latency_ms": round(l, 1), "citations": c, "timestamp": t}
                for q, i, l, c, t in recent
            ],
        }
