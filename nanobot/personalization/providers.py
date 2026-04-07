"""Provider registry for future context-variable integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from nanobot.personalization.contracts import RuntimeState, SurfaceCandidate


class ContextVariableProvider(ABC):
    """Base provider for one family of adaptive context variables."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider name."""

    def supports(self, state: RuntimeState) -> bool:
        """Whether this provider should run for the current turn."""
        return True

    @abstractmethod
    def generate(self, state: RuntimeState) -> list[SurfaceCandidate]:
        """Produce typed surface candidates for personalization routing."""


class ContextVariableRegistry:
    """Registry used to add new context-variable providers without touching the router."""

    def __init__(self) -> None:
        self._providers: list[ContextVariableProvider] = []

    def register(self, provider: ContextVariableProvider) -> None:
        self._providers.append(provider)

    def providers(self) -> list[str]:
        return [provider.name for provider in self._providers]

    def generate(self, state: RuntimeState) -> list[SurfaceCandidate]:
        out: list[SurfaceCandidate] = []
        for provider in self._providers:
            if not provider.supports(state):
                continue
            out.extend(provider.generate(state))
        return out
