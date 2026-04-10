"""Base classes for knowledge-source integrations and layered storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha1
from typing import Any

from nanobot.knowledge.contracts import (
    KnowledgeArtifact,
    KnowledgeCandidate,
    KnowledgeClaimType,
    KnowledgeIngestRequest,
    KnowledgeIngestResult,
    KnowledgeKind,
    KnowledgeLayer,
    KnowledgeQuery,
    KnowledgeRetentionDecision,
    KnowledgeStatus,
    KnowledgeSourceSpec,
)


class KnowledgeSourceAdapter(ABC):
    """Adapter for one concrete knowledge source platform or protocol."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable adapter name."""

    @abstractmethod
    def supports(self, source: KnowledgeSourceSpec) -> bool:
        """Whether this adapter can handle the given source descriptor."""

    @abstractmethod
    def ingest(self, request: KnowledgeIngestRequest) -> KnowledgeIngestResult:
        """Normalize raw source payload into typed artifacts."""

    def retrieve(self, query: KnowledgeQuery) -> list[KnowledgeCandidate]:
        """Optional direct retrieval from the source backend."""
        return []


class BaseKnowledgeSourceAdapter(KnowledgeSourceAdapter):
    """Common helpers for concrete knowledge adapters."""

    supported_platforms: tuple[str, ...] = ()
    supported_content_types: tuple[str, ...] = ()

    def supports(self, source: KnowledgeSourceSpec) -> bool:
        if self.supported_platforms and source.platform not in self.supported_platforms:
            return False
        if self.supported_content_types and source.content_types:
            return any(content_type in self.supported_content_types for content_type in source.content_types)
        return True

    @staticmethod
    def coerce_text(payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="ignore")
        if isinstance(payload, dict):
            parts = [f"{key}: {value}" for key, value in payload.items()]
            return "\n".join(parts)
        if isinstance(payload, list):
            return "\n".join(BaseKnowledgeSourceAdapter.coerce_text(item) for item in payload)
        return str(payload)

    def build_artifact(
        self,
        *,
        source: KnowledgeSourceSpec,
        layer: KnowledgeLayer,
        title: str,
        content: str,
        kind: KnowledgeKind = "archive",
        status: KnowledgeStatus = "active",
        claim_type: KnowledgeClaimType = "fact",
        artifact_id: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
        citations: list[str] | None = None,
        derived_from: list[str] | None = None,
        related_notes: list[str] | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeArtifact:
        if artifact_id is None:
            digest = sha1(f"{source.source_id}:{layer}:{title}:{content[:128]}".encode("utf-8")).hexdigest()[:16]
            artifact_id = f"{source.source_id}:{layer}:{digest}"
        return KnowledgeArtifact(
            artifact_id=artifact_id,
            source_id=source.source_id,
            layer=layer,
            title=title,
            content=content,
            kind=kind,
            status=status,
            claim_type=claim_type,
            summary=summary,
            tags=list(tags or []),
            links=list(links or []),
            citations=list(citations or []),
            derived_from=list(derived_from or []),
            related_notes=list(related_notes or []),
            confidence=confidence,
            metadata=dict(metadata or {}),
        )


class FilesystemKnowledgeAdapter(BaseKnowledgeSourceAdapter):
    """Base class for filesystem-backed or vault-backed knowledge sources."""

    supported_platforms = ("filesystem", "obsidian")


class WebKnowledgeAdapter(BaseKnowledgeSourceAdapter):
    """Base class for crawled or fetched web knowledge sources."""

    supported_platforms = ("web",)


class MCPKnowledgeAdapter(BaseKnowledgeSourceAdapter):
    """Base class for MCP-backed knowledge sources."""

    supported_platforms = ("mcp",)


class APIKnowledgeAdapter(BaseKnowledgeSourceAdapter):
    """Base class for API-backed knowledge sources."""

    supported_platforms = ("api",)


class CLIKnowledgeAdapter(BaseKnowledgeSourceAdapter):
    """Base class for external CLI-backed knowledge sources."""

    supported_platforms = ("cli",)


class KnowledgeStore(ABC):
    """Storage backend for layered knowledge artifacts."""

    @abstractmethod
    def write_artifacts(self, artifacts: list[KnowledgeArtifact]) -> None:
        """Persist artifacts into the store."""

    @abstractmethod
    def get_artifact(self, artifact_id: str) -> KnowledgeArtifact | None:
        """Fetch one artifact by id."""

    @abstractmethod
    def query(self, query: KnowledgeQuery) -> list[KnowledgeCandidate]:
        """Retrieve relevant artifacts from the store."""


class KnowledgeCompiler(ABC):
    """Transforms lower-level artifacts into higher-level compiled knowledge."""

    @abstractmethod
    def compile(
        self,
        artifacts: list[KnowledgeArtifact],
        *,
        target_layer: KnowledgeLayer,
        source: KnowledgeSourceSpec,
    ) -> list[KnowledgeArtifact]:
        """Compile incoming artifacts into the target layer."""


class KnowledgeRetentionPolicy(ABC):
    """Decides whether new knowledge should be retained or promoted."""

    @abstractmethod
    def decide(
        self,
        request: KnowledgeIngestRequest,
        result: KnowledgeIngestResult,
    ) -> KnowledgeRetentionDecision:
        """Return admission and target-layer policy for one ingest."""
