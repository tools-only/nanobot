"""Shortlist stage for lightweight online personalization."""

from __future__ import annotations

from collections import defaultdict

from nanobot.personalization.contracts import RuntimeState, SurfaceCandidate

_SHORTLIST_BUDGETS = {
    "context_evidence": 3,
    "capability_exposure": 3,
    "acquisition_policy": 2,
    "interaction_hint": 2,
    "knowledge_exposure": 2,
}


class CandidateShortlister:
    """Reduce the candidate space before any online reward comparison."""

    def shortlist(self, state: RuntimeState, candidates: list[SurfaceCandidate]) -> list[SurfaceCandidate]:
        del state  # reserved for future state-aware shortlist logic
        grouped: dict[str, list[SurfaceCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[candidate.surface].append(candidate)

        shortlisted: list[SurfaceCandidate] = []
        for surface, budget in _SHORTLIST_BUDGETS.items():
            ranked = sorted(grouped.get(surface, []), key=lambda item: (-item.score, item.item_key))
            shortlisted.extend(ranked[:budget])
        return shortlisted
