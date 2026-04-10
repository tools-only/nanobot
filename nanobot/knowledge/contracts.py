"""Typed contracts for layered knowledge management."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


KnowledgeLayer = Literal["raw", "parsed", "canonical", "synthesis"]
KnowledgeKind = Literal["archive", "concept", "topic", "fusion"]
KnowledgeStatus = Literal["active", "queued", "reviewed", "deprecated"]
KnowledgeClaimType = Literal["fact", "synthesis", "hypothesis"]
KnowledgePlatform = Literal["filesystem", "web", "mcp", "obsidian", "api", "cli", "custom"]


@dataclass
class KnowledgeSourceSpec:
    """Descriptor for one knowledge source integration."""

    source_id: str
    platform: KnowledgePlatform
    namespace: str = "shared"
    mcp_server: str | None = None
    content_types: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeArtifact:
    """Normalized knowledge unit used across ingestion, storage, and retrieval."""

    artifact_id: str
    source_id: str
    layer: KnowledgeLayer
    title: str
    content: str
    kind: KnowledgeKind = "archive"
    status: KnowledgeStatus = "active"
    claim_type: KnowledgeClaimType = "fact"
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    related_notes: list[str] = field(default_factory=list)
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeIngestRequest:
    """Raw input destined for a knowledge adapter."""

    source: KnowledgeSourceSpec
    payload: Any
    content_type: str | None = None
    external_id: str | None = None
    user_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source"] = self.source.to_dict()
        return payload


@dataclass
class KnowledgeIngestResult:
    """Normalized output produced by a knowledge adapter/compiler."""

    source: KnowledgeSourceSpec
    artifacts: list[KnowledgeArtifact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


@dataclass
class KnowledgeQuery:
    """Retrieval query against one or more knowledge layers."""

    query: str
    user_key: str | None = None
    namespace: str = "shared"
    layers: list[KnowledgeLayer] = field(default_factory=lambda: ["canonical", "synthesis"])
    kinds: list[KnowledgeKind] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    max_results: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeCandidate:
    """Retrieved knowledge candidate for downstream personalization or context assembly."""

    artifact: KnowledgeArtifact
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact.to_dict(),
            "score": self.score,
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }


@dataclass
class KnowledgeRetentionDecision:
    """Admission or routing decision for one ingest request/result."""

    admitted: bool
    target_layer: KnowledgeLayer = "raw"
    reason: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
