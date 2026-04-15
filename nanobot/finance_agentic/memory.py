"""Shared and private memory primitives for finance agentic orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nanobot.finance_agentic.contracts import RoundtableMessage

_DEFAULT_PRIVATE_MEMORY: dict[str, list[dict[str, object]]] = {
    "news": [
        {
            "doc_id": "news-default-1",
            "title": "Prioritize verified event facts",
            "summary": "Start from entities, timing, and the strongest source-backed evidence before moving to interpretation.",
            "tags": ["evidence", "source", "event"],
        }
    ],
    "asset": [
        {
            "doc_id": "asset-default-1",
            "title": "Short-horizon asset template",
            "summary": "When signal strength is weak or contradictory, prefer neutral or lower confidence instead of forcing direction.",
            "tags": ["asset", "confidence", "neutral"],
        }
    ],
    "risk": [
        {
            "doc_id": "risk-default-1",
            "title": "Risk calibration template",
            "summary": "Elevated volatility, risk-off tone, and tape conflict should reduce confidence or move the thesis toward neutral.",
            "tags": ["risk", "volatility", "confidence"],
        }
    ],
    "critic": [
        {
            "doc_id": "critic-default-1",
            "title": "Critic standard",
            "summary": "Critic should identify blocking issues, assign targeted repairs, and stop the loop when additional rounds add little information.",
            "tags": ["critic", "convergence", "repair"],
        }
    ],
}


@dataclass(slots=True)
class SharedFinanceMemory:
    event_object: dict
    market_summary: dict
    public_evidence: list[str] = field(default_factory=list)
    discussion_messages: list[RoundtableMessage] = field(default_factory=list)
    open_issues: list[str] = field(default_factory=list)
    resolved_issues: list[str] = field(default_factory=list)
    final_conclusion: dict | None = None

    def add_public_evidence(self, lines: list[str]) -> None:
        for line in lines:
            if line not in self.public_evidence:
                self.public_evidence.append(line)

    def add_roundtable_messages(self, messages: list[RoundtableMessage]) -> None:
        self.discussion_messages.extend(messages)

    def update_open_issues(self, issues: list[str]) -> None:
        deduped: list[str] = []
        for issue in issues:
            if issue and issue not in deduped and issue not in self.resolved_issues:
                deduped.append(issue)
        self.open_issues = deduped

    def resolve_issues(self, issues: list[str]) -> None:
        for issue in issues:
            if issue in self.open_issues:
                self.open_issues.remove(issue)
            if issue and issue not in self.resolved_issues:
                self.resolved_issues.append(issue)

    def set_final_conclusion(self, payload: dict) -> None:
        self.final_conclusion = payload

    def snapshot(self) -> dict:
        return {
            "event_object": dict(self.event_object),
            "market_summary": dict(self.market_summary),
            "public_evidence": list(self.public_evidence),
            "discussion_messages": [asdict(message) for message in self.discussion_messages],
            "open_issues": list(self.open_issues),
            "resolved_issues": list(self.resolved_issues),
            "final_conclusion": self.final_conclusion,
        }


class PrivateFinanceMemory:
    """Workspace-backed private memory namespaces with built-in defaults."""

    def __init__(self, workspace: Path):
        self.root = workspace / "finance_agentic" / "memory"

    def retrieve(self, namespace: str, query_terms: list[str], limit: int = 3) -> list[dict[str, object]]:
        docs = list(_DEFAULT_PRIVATE_MEMORY.get(namespace, []))
        path = self.root / f"{namespace}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    docs.extend(item for item in payload if isinstance(item, dict))
            except Exception:
                pass
        if not docs:
            return []
        lowered = " ".join(query_terms).lower()
        scored: list[tuple[int, dict[str, object]]] = []
        for doc in docs:
            haystack = " ".join(
                [
                    str(doc.get("title", "")),
                    str(doc.get("summary", "")),
                    " ".join(str(tag) for tag in doc.get("tags", [])),
                ]
            ).lower()
            score = sum(1 for token in lowered.split() if token and token in haystack)
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [doc for score, doc in scored[:limit] if score > 0] or docs[:limit]
