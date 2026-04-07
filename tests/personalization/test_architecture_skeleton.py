from nanobot.knowledge import (
    BaseKnowledgeSourceAdapter,
    InMemoryKnowledgeStore,
    KnowledgeIngestRequest,
    KnowledgeIngestResult,
    KnowledgeQuery,
    KnowledgeRuntime,
    KnowledgeSourceSpec,
)
from nanobot.memory_layers import LayeredMemoryManager, MemoryObservation, MemoryQuery
from nanobot.personalization.candidate_generators import CandidateGenerators
from nanobot.personalization.contracts import RuntimeState
from nanobot.personalization.providers import ContextVariableProvider, ContextVariableRegistry
from nanobot.personalization.score_tables import ScoreTables


class DummyKnowledgeAdapter(BaseKnowledgeSourceAdapter):
    name = "dummy"
    supported_platforms = ("custom",)

    def ingest(self, request: KnowledgeIngestRequest) -> KnowledgeIngestResult:
        artifact = self.build_artifact(
            source=request.source,
            layer="raw",
            title="Dummy Note",
            content=self.coerce_text(request.payload),
            summary="dummy",
            tags=["demo"],
        )
        return KnowledgeIngestResult(source=request.source, artifacts=[artifact])


class DummyProvider(ContextVariableProvider):
    @property
    def name(self) -> str:
        return "dummy-provider"

    def generate(self, state: RuntimeState):
        from nanobot.personalization.contracts import SurfaceCandidate

        return [
            SurfaceCandidate(
                candidate_id="dummy-knowledge",
                surface="knowledge_exposure",
                slot="knowledge_note",
                item_key="dummy_knowledge_note",
                title="Dummy Knowledge",
                summary="Future knowledge providers can emit candidates here.",
                score=0.9,
                reasons=["provider_registry"],
            )
        ]


def test_knowledge_runtime_ingests_and_queries() -> None:
    runtime = KnowledgeRuntime(store=InMemoryKnowledgeStore())
    runtime.register_adapter(DummyKnowledgeAdapter())

    source = KnowledgeSourceSpec(source_id="demo", platform="custom")
    result = runtime.ingest(KnowledgeIngestRequest(source=source, payload="hello world", content_type="text/plain"))

    assert result.artifacts
    matches = runtime.retrieve(KnowledgeQuery(query="hello", layers=["parsed"]))
    assert matches


def test_layered_memory_manager_materializes_units() -> None:
    memory = LayeredMemoryManager()
    units = memory.observe(MemoryObservation(user_key="cli:user", session_key="cli:test", content="I like travel"))

    assert len(units) == 2
    matches = memory.retrieve(MemoryQuery(user_key="cli:user", session_key="cli:test", query="travel"))
    assert matches


def test_candidate_generators_accept_external_providers(tmp_path) -> None:
    registry = ContextVariableRegistry()
    registry.register(DummyProvider())
    generators = CandidateGenerators(ScoreTables(tmp_path), providers=registry)
    state = RuntimeState(
        user_key="cli:user",
        session_key="cli:test",
        channel="cli",
        chat_id="direct",
        sender_id="user",
        current_message="hello",
    )

    candidates = generators.generate(state)
    assert any(candidate.surface == "knowledge_exposure" for candidate in candidates)
