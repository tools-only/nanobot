"""Typed contracts for personalization middleware."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SurfaceType = Literal[
    "context_evidence",
    "capability_exposure",
    "acquisition_policy",
    "interaction_hint",
    "knowledge_exposure",
]


@dataclass
class UserProfileSnapshot:
    """A compact user-level personalization snapshot."""

    user_key: str
    topic_counts: dict[str, int] = field(default_factory=dict)
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeState:
    """Normalized per-turn state for candidate generation and routing."""

    user_key: str
    session_key: str
    channel: str
    chat_id: str
    sender_id: str
    current_message: str
    recent_user_messages: list[str] = field(default_factory=list)
    active_skills: list[dict[str, str]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    profile: UserProfileSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.profile is not None:
            payload["profile"] = self.profile.to_dict()
        return payload


@dataclass
class SurfaceCandidate:
    """A candidate exposure item for a specific input surface."""

    candidate_id: str
    surface: SurfaceType
    slot: str
    item_key: str
    title: str
    summary: str
    score: float = 0.0
    online_eval_score: float | None = None
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExposurePlan:
    """Selected exposure slate plus compiled adaptive context blocks."""

    state: RuntimeState
    candidates: list[SurfaceCandidate] = field(default_factory=list)
    shortlisted_items: list[SurfaceCandidate] = field(default_factory=list)
    selected_items: list[SurfaceCandidate] = field(default_factory=list)
    dynamic_blocks: list[str] = field(default_factory=list)
    online_eval: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "shortlisted_items": [item.to_dict() for item in self.shortlisted_items],
            "selected_items": [item.to_dict() for item in self.selected_items],
            "dynamic_blocks": list(self.dynamic_blocks),
            "online_eval": dict(self.online_eval),
        }


@dataclass
class RewardAssignmentRequest:
    """A pending reward-assignment task for asynchronous judging."""

    turn_id: str
    user_key: str
    session_key: str
    status: str
    candidate_items: list[dict[str, Any]] = field(default_factory=list)
    shortlisted_items: list[dict[str, Any]] = field(default_factory=list)
    selected_items: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    feedback_signals: dict[str, Any] = field(default_factory=dict)
    proxy_metrics: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    online_eval: dict[str, Any] = field(default_factory=dict)
    final_content: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
