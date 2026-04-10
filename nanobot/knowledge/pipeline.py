"""Knowledge runtime skeleton with adapter registry and lightweight defaults."""

from __future__ import annotations

from pathlib import Path

from nanobot.knowledge.base import (
    KnowledgeCompiler,
    KnowledgeRetentionPolicy,
    KnowledgeSourceAdapter,
    KnowledgeStore,
)
from nanobot.knowledge.contracts import (
    KnowledgeArtifact,
    KnowledgeCandidate,
    KnowledgeIngestRequest,
    KnowledgeIngestResult,
    KnowledgeQuery,
    KnowledgeRetentionDecision,
    KnowledgeSourceSpec,
)


class KnowledgeAdapterRegistry:
    """Registry for source-specific knowledge adapters."""

    def __init__(self) -> None:
        self._adapters: list[KnowledgeSourceAdapter] = []

    def register(self, adapter: KnowledgeSourceAdapter) -> None:
        self._adapters.append(adapter)

    def resolve(self, source: KnowledgeSourceSpec) -> KnowledgeSourceAdapter | None:
        for adapter in self._adapters:
            if adapter.supports(source):
                return adapter
        return None

    def list_adapters(self) -> list[str]:
        return [adapter.name for adapter in self._adapters]


class NullKnowledgeStore(KnowledgeStore):
    """Default no-op store used until a real backend is configured."""

    def write_artifacts(self, artifacts: list[KnowledgeArtifact]) -> None:
        return None

    def get_artifact(self, artifact_id: str) -> KnowledgeArtifact | None:
        return None

    def query(self, query: KnowledgeQuery) -> list[KnowledgeCandidate]:
        return []


class InMemoryKnowledgeStore(KnowledgeStore):
    """Small in-memory store useful for tests and lightweight prototypes."""

    def __init__(self) -> None:
        self._artifacts: dict[str, KnowledgeArtifact] = {}

    def write_artifacts(self, artifacts: list[KnowledgeArtifact]) -> None:
        for artifact in artifacts:
            self._artifacts[artifact.artifact_id] = artifact

    def get_artifact(self, artifact_id: str) -> KnowledgeArtifact | None:
        return self._artifacts.get(artifact_id)

    def query(self, query: KnowledgeQuery) -> list[KnowledgeCandidate]:
        matches: list[KnowledgeCandidate] = []
        query_text = query.query.lower().strip()
        for artifact in self._artifacts.values():
            if artifact.layer not in query.layers:
                continue
            if query.kinds and artifact.kind not in query.kinds:
                continue
            haystack = f"{artifact.title}\n{artifact.summary or ''}\n{artifact.content}".lower()
            score = 0.0
            if query_text and query_text in haystack:
                score += 1.0
            if query.tags:
                overlap = len(set(query.tags) & set(artifact.tags))
                score += overlap * 0.25
            if score <= 0:
                continue
            matches.append(KnowledgeCandidate(artifact=artifact, score=score, reasons=["in_memory_match"]))
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[: query.max_results]


class PassthroughKnowledgeCompiler(KnowledgeCompiler):
    """Default compiler that only rewrites the layer field."""

    def compile(
        self,
        artifacts: list[KnowledgeArtifact],
        *,
        target_layer,
        source: KnowledgeSourceSpec,
    ) -> list[KnowledgeArtifact]:
        out: list[KnowledgeArtifact] = []
        for artifact in artifacts:
            if artifact.layer == target_layer:
                out.append(artifact)
                continue
            out.append(KnowledgeArtifact(
                artifact_id=f"{artifact.artifact_id}:{target_layer}",
                source_id=artifact.source_id,
                layer=target_layer,
                title=artifact.title,
                content=artifact.content,
                kind=artifact.kind,
                status=artifact.status,
                claim_type=artifact.claim_type,
                summary=artifact.summary,
                tags=list(artifact.tags),
                links=list(artifact.links),
                citations=list(artifact.citations),
                derived_from=list(artifact.derived_from),
                related_notes=list(artifact.related_notes),
                confidence=artifact.confidence,
                metadata=dict(artifact.metadata),
            ))
        return out


class SimpleKnowledgeRetentionPolicy(KnowledgeRetentionPolicy):
    """Lightweight admission policy for the initial architecture skeleton."""

    def decide(
        self,
        request: KnowledgeIngestRequest,
        result: KnowledgeIngestResult,
    ) -> KnowledgeRetentionDecision:
        text_size = sum(len(artifact.content.strip()) for artifact in result.artifacts)
        if not result.artifacts or text_size == 0:
            return KnowledgeRetentionDecision(admitted=False, target_layer="raw", reason="empty_ingest")
        target_layer = "parsed" if request.content_type else "raw"
        return KnowledgeRetentionDecision(admitted=True, target_layer=target_layer, reason="default_admit")


class KnowledgeRuntime:
    """Top-level knowledge runtime for heterogeneous sources and future compilers."""

    def __init__(
        self,
        workspace: Path | None = None,
        *,
        store: KnowledgeStore | None = None,
        compiler: KnowledgeCompiler | None = None,
        retention: KnowledgeRetentionPolicy | None = None,
        registry: KnowledgeAdapterRegistry | None = None,
    ) -> None:
        self.workspace = workspace
        self.store = store or NullKnowledgeStore()
        self.compiler = compiler or PassthroughKnowledgeCompiler()
        self.retention = retention or SimpleKnowledgeRetentionPolicy()
        self.registry = registry or KnowledgeAdapterRegistry()

    def register_adapter(self, adapter: KnowledgeSourceAdapter) -> None:
        self.registry.register(adapter)

    def ingest(self, request: KnowledgeIngestRequest) -> KnowledgeIngestResult:
        adapter = self.registry.resolve(request.source)
        if adapter is None:
            return KnowledgeIngestResult(
                source=request.source,
                warnings=[f"no_adapter:{request.source.platform}:{request.source.source_id}"],
            )

        result = adapter.ingest(request)
        decision = self.retention.decide(request, result)
        if not decision.admitted:
            result.warnings.append(f"retention_rejected:{decision.reason}")
            return result

        if result.metadata.get("preserve_layers"):
            artifacts = result.artifacts
        else:
            artifacts = self.compiler.compile(
                result.artifacts,
                target_layer=decision.target_layer,
                source=request.source,
            )
        self.store.write_artifacts(artifacts)
        return KnowledgeIngestResult(
            source=result.source,
            artifacts=artifacts,
            warnings=list(result.warnings),
            metadata={**result.metadata, "retention": decision.to_dict()},
        )

    def retrieve(self, query: KnowledgeQuery) -> list[KnowledgeCandidate]:
        return self.store.query(query)
