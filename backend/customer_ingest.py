"""
customer_ingest.py
Parses the five synthetic dataset files (accounts, issues, feature_requests,
tasks, meeting_notes) into typed entities + relationship edges that the
graph_engine can load.

No LLM calls happen here — this is pure deterministic markdown parsing so
ingestion is fast, reproducible, and testable.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from config import CUSTOMER_FILES, canonicalize_feature


# ---------------------------------------------------------------------------
# Entity dataclasses
# ---------------------------------------------------------------------------
@dataclass
class Account:
    id: str
    name: str
    industry: str
    region: str
    tier: str
    health: str
    arr: int
    owner: str
    devices: list[str]


@dataclass
class Issue:
    id: str
    account_name: str
    category: str
    status: str
    title: str


@dataclass
class FeatureRequest:
    id: str
    title: str
    product_area: str
    status: str
    accounts: list[str]
    mentions: int
    revenue_impact: int
    canonical_feature: str | None = None


@dataclass
class Task:
    id: str
    account_name: str
    title: str
    assignee: str
    priority: str
    status: str
    due: str | None


@dataclass
class MeetingNote:
    id: str
    account_name: str
    topic: str
    attendees: list[str]
    date: str | None
    action_items: list[str]


@dataclass
class Person:
    name: str
    roles: set[str] = field(default_factory=set)  # e.g. {"owner"}, {"attendee"}, {"assignee"}


@dataclass
class IngestResult:
    accounts: dict[str, Account]
    issues: list[Issue]
    feature_requests: list[FeatureRequest]
    tasks: list[Task]
    meeting_notes: list[MeetingNote]
    people: dict[str, Person]

    def stats(self) -> dict:
        return {
            "accounts": len(self.accounts),
            "issues": len(self.issues),
            "feature_requests": len(self.feature_requests),
            "tasks": len(self.tasks),
            "meeting_notes": len(self.meeting_notes),
            "people": len(self.people),
        }


# ---------------------------------------------------------------------------
# Generic markdown-table parser
# ---------------------------------------------------------------------------
def _parse_md_table(text: str) -> list[dict[str, str]]:
    """Parses a single GitHub-flavored markdown table into a list of row dicts."""
    lines = [l for l in text.splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:  # skip header + separator row
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def _money_to_int(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s) or 0)


def _split_list(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Per-file parsers
# ---------------------------------------------------------------------------
def parse_accounts(path: Path) -> dict[str, Account]:
    rows = _parse_md_table(path.read_text(encoding="utf-8"))
    accounts: dict[str, Account] = {}
    for r in rows:
        acc = Account(
            id=r["ID"],
            name=r["Name"],
            industry=r["Industry"],
            region=r["Region"],
            tier=r["Tier"],
            health=r["Health"],
            arr=_money_to_int(r["ARR"]),
            owner=r["Owner"],
            devices=_split_list(r["Devices"]),
        )
        accounts[acc.name] = acc
    return accounts


def parse_issues(path: Path) -> list[Issue]:
    rows = _parse_md_table(path.read_text(encoding="utf-8"))
    return [
        Issue(
            id=r["ID"],
            account_name=r["Account"],
            category=r["Category"],
            status=r["Status"],
            title=r["Title"],
        )
        for r in rows
    ]


def parse_tasks(path: Path) -> list[Task]:
    rows = _parse_md_table(path.read_text(encoding="utf-8"))
    return [
        Task(
            id=r["ID"],
            account_name=r["Account"],
            title=r["Title"],
            assignee=r["Assignee"],
            priority=r["Priority"],
            status=r["Status"],
            due=r.get("Due") or None,
        )
        for r in rows
    ]


def parse_feature_requests(path: Path) -> list[FeatureRequest]:
    rows = _parse_md_table(path.read_text(encoding="utf-8"))
    out = []
    for i, r in enumerate(rows, start=1):
        title = r["Title"]
        out.append(
            FeatureRequest(
                id=f"FR-{i:04d}",
                title=title,
                product_area=r["Product Area"],
                status=r["Status"],
                accounts=_split_list(r["Accounts Requesting"]),
                mentions=int(r["Mentions"]),
                revenue_impact=_money_to_int(r["Est. Revenue Impact"]),
                canonical_feature=canonicalize_feature(title),
            )
        )
    return out


_MTG_HEADER_RE = re.compile(r"^##\s+(MTG-\d+):\s*(.+)$")
_FIELD_RE = re.compile(r"^\*\*(.+?):\*\*\s*(.*)$")


def parse_meeting_notes(path: Path) -> list[MeetingNote]:
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^## MTG-)", text, flags=re.MULTILINE)
    notes: list[MeetingNote] = []
    for block in blocks:
        first_line = block.splitlines()[0] if block.splitlines() else ""
        m = _MTG_HEADER_RE.match(first_line)
        if not m:
            continue
        mtg_id, account_name = m.group(1), m.group(2).strip()
        topic = ""
        attendees: list[str] = []
        date = None
        action_items: list[str] = []
        in_actions = False
        for line in block.splitlines():
            fm = _FIELD_RE.match(line.strip())
            if fm:
                key, val = fm.group(1).lower(), fm.group(2).strip()
                in_actions = key == "action items"
                if key == "topic":
                    topic = val
                elif key == "attendees":
                    attendees = _split_list(val)
                elif key == "date":
                    date = val
                continue
            if in_actions and line.strip().startswith("-"):
                action_items.append(line.strip().lstrip("- ").strip())
        notes.append(
            MeetingNote(
                id=mtg_id,
                account_name=account_name,
                topic=topic,
                attendees=attendees,
                date=date,
                action_items=action_items,
            )
        )
    return notes


# ---------------------------------------------------------------------------
# Top-level ingest
# ---------------------------------------------------------------------------
def ingest_all(files: dict[str, Path] | None = None) -> IngestResult:
    files = files or CUSTOMER_FILES
    accounts = parse_accounts(files["accounts"])
    issues = parse_issues(files["issues"])
    feature_requests = parse_feature_requests(files["feature_requests"])
    tasks = parse_tasks(files["tasks"])
    meeting_notes = parse_meeting_notes(files["meeting_notes"])

    people: dict[str, Person] = {}

    def add_person(name: str, role: str):
        if not name:
            return
        p = people.setdefault(name, Person(name=name))
        p.roles.add(role)

    for a in accounts.values():
        add_person(a.owner, "owner")
    for t in tasks:
        add_person(t.assignee, "assignee")
    for mn in meeting_notes:
        for att in mn.attendees:
            add_person(att, "attendee")

    return IngestResult(
        accounts=accounts,
        issues=issues,
        feature_requests=feature_requests,
        tasks=tasks,
        meeting_notes=meeting_notes,
        people=people,
    )


if __name__ == "__main__":
    result = ingest_all()
    print("Ingestion stats:", result.stats())
    # Spot-check a few records
    sample_acc = next(iter(result.accounts.values()))
    print("Sample account:", asdict(sample_acc))
    print("Sample issue:", asdict(result.issues[0]))
    print("Sample feature request:", asdict(result.feature_requests[0]))
    print("Sample meeting note:", asdict(result.meeting_notes[0]))
    print("Sample task:", asdict(result.tasks[0]))
