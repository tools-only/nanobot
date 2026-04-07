"""Typed contracts for layered memory evolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


MemoryLayer = Literal["working", "episodic", "semantic", "policy"]


@dataclass
class MemoryUnit:
    """Normalized memory object across all layers."""

    unit_id: str
    layer: MemoryLayer
    user_key: str
    session_key: str | None = None
    title: str = ""
    content: str = ""
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryObservation:
    """Observed runtime signal that may create or update memory."""

    user_key: str
    session_key: str
    content: str
    role: str = "user"
    outcome: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryQuery:
    """Retrieval query over one or more memory layers."""

    user_key: str
    query: str
    session_key: str | None = None
    layers: list[MemoryLayer] = field(default_factory=lambda: ["working", "semantic"])
    tags: list[str] = field(default_factory=list)
    max_results: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryCandidate:
    """Retrieved memory candidate used by downstream routers or compilers."""

    unit: MemoryUnit
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit.to_dict(),
            "score": self.score,
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }


@dataclass
class MemoryPromotionDecision:
    """Decision to keep, promote, or demote a memory unit."""

    unit_id: str
    from_layer: MemoryLayer
    to_layer: MemoryLayer | None
    action: Literal["keep", "promote", "demote", "drop"]
    reason: str
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
