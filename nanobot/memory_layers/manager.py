"""Layered memory runtime with lightweight defaults."""

from __future__ import annotations

from nanobot.memory_layers.base import BaseMemoryLayerStore, MemoryEvolutionPolicy, MemoryLayerStore
from nanobot.memory_layers.contracts import (
    MemoryCandidate,
    MemoryObservation,
    MemoryPromotionDecision,
    MemoryQuery,
    MemoryUnit,
)


class InMemoryLayerStore(BaseMemoryLayerStore):
    """Simple in-memory layered store for bootstrapping the architecture."""

    def __init__(self) -> None:
        self._units: dict[str, MemoryUnit] = {}

    def upsert_units(self, units: list[MemoryUnit]) -> None:
        for unit in units:
            self._units[unit.unit_id] = unit

    def get_unit(self, unit_id: str) -> MemoryUnit | None:
        return self._units.get(unit_id)

    def query(self, query: MemoryQuery) -> list[MemoryCandidate]:
        query_text = query.query.lower().strip()
        out: list[MemoryCandidate] = []
        for unit in self._units.values():
            if unit.user_key != query.user_key:
                continue
            if unit.layer not in query.layers:
                continue
            if query.session_key and unit.session_key and unit.session_key != query.session_key:
                continue
            haystack = f"{unit.title}\n{unit.summary or ''}\n{unit.content}".lower()
            score = 0.0
            if query_text and query_text in haystack:
                score += 1.0
            if query.tags:
                score += len(set(query.tags) & set(unit.tags)) * 0.25
            if score <= 0:
                continue
            out.append(MemoryCandidate(unit=unit, score=score, reasons=["in_memory_match"]))
        out.sort(key=lambda item: item.score, reverse=True)
        return out[: query.max_results]

    def prune(self) -> int:
        return 0


class SimpleMemoryEvolutionPolicy(MemoryEvolutionPolicy):
    """Small default evolution policy used to keep the initial skeleton lightweight."""

    def materialize(self, observation: MemoryObservation) -> list[MemoryUnit]:
        text = observation.content.strip()
        if not text:
            return []
        working_id = BaseMemoryLayerStore.build_unit_id(observation.user_key, observation.session_key, "working", text[:64])
        episodic_id = BaseMemoryLayerStore.build_unit_id(observation.user_key, observation.session_key, "episodic", text[:64])
        return [
            MemoryUnit(
                unit_id=working_id,
                layer="working",
                user_key=observation.user_key,
                session_key=observation.session_key,
                title="Working Turn Context",
                content=text,
                summary=text[:240],
                metadata={"role": observation.role, **observation.metadata},
            ),
            MemoryUnit(
                unit_id=episodic_id,
                layer="episodic",
                user_key=observation.user_key,
                session_key=observation.session_key,
                title="Interaction Episode",
                content=text,
                summary=text[:240],
                metadata={"role": observation.role, "outcome": observation.outcome, **observation.metadata},
            ),
        ]

    def decide_promotions(self, units: list[MemoryUnit]) -> list[MemoryPromotionDecision]:
        decisions: list[MemoryPromotionDecision] = []
        for unit in units:
            if unit.layer == "working":
                decisions.append(MemoryPromotionDecision(
                    unit_id=unit.unit_id,
                    from_layer="working",
                    to_layer="episodic",
                    action="promote",
                    reason="working_to_episode",
                    confidence=0.5,
                ))
                continue
            decisions.append(MemoryPromotionDecision(
                unit_id=unit.unit_id,
                from_layer=unit.layer,
                to_layer=unit.layer,
                action="keep",
                reason="default_keep",
                confidence=0.2,
            ))
        return decisions


class LayeredMemoryManager:
    """Owns layered memory stores and evolution hooks for future adapters."""

    def __init__(
        self,
        *,
        store: MemoryLayerStore | None = None,
        evolution: MemoryEvolutionPolicy | None = None,
    ) -> None:
        self.store = store or InMemoryLayerStore()
        self.evolution = evolution or SimpleMemoryEvolutionPolicy()

    def observe(self, observation: MemoryObservation) -> list[MemoryUnit]:
        units = self.evolution.materialize(observation)
        if units:
            self.store.upsert_units(units)
        return units

    def retrieve(self, query: MemoryQuery) -> list[MemoryCandidate]:
        return self.store.query(query)

    def evaluate_promotions(self, units: list[MemoryUnit]) -> list[MemoryPromotionDecision]:
        return self.evolution.decide_promotions(units)

    def prune(self) -> int:
        return self.store.prune()
