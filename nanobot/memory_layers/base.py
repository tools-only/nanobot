"""Base abstractions for layered memory stores and evolution policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha1

from nanobot.memory_layers.contracts import (
    MemoryCandidate,
    MemoryObservation,
    MemoryPromotionDecision,
    MemoryQuery,
    MemoryUnit,
)


class MemoryLayerStore(ABC):
    """Storage backend for one or more memory layers."""

    @abstractmethod
    def upsert_units(self, units: list[MemoryUnit]) -> None:
        """Persist or replace memory units."""

    @abstractmethod
    def get_unit(self, unit_id: str) -> MemoryUnit | None:
        """Read one memory unit by id."""

    @abstractmethod
    def query(self, query: MemoryQuery) -> list[MemoryCandidate]:
        """Retrieve relevant memory units."""

    @abstractmethod
    def prune(self) -> int:
        """Remove expired or obsolete units and return the number pruned."""


class BaseMemoryLayerStore(MemoryLayerStore):
    """Helper mixin for concrete memory stores."""

    @staticmethod
    def build_unit_id(*parts: str) -> str:
        digest = sha1(":".join(parts).encode("utf-8")).hexdigest()[:16]
        return f"mem:{digest}"


class MemoryEvolutionPolicy(ABC):
    """Policy for creating and evolving memory units across layers."""

    @abstractmethod
    def materialize(self, observation: MemoryObservation) -> list[MemoryUnit]:
        """Create initial units from one observation."""

    @abstractmethod
    def decide_promotions(self, units: list[MemoryUnit]) -> list[MemoryPromotionDecision]:
        """Return keep/promote/demote decisions for the provided units."""
