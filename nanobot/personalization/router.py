"""Budget-aware typed router for surface candidates."""

from __future__ import annotations

from collections import defaultdict

from nanobot.personalization.contracts import ExposurePlan, RuntimeState, SurfaceCandidate

_SURFACE_BUDGETS = {
    "context_evidence": 2,
    "capability_exposure": 2,
    "acquisition_policy": 1,
    "interaction_hint": 1,
}


class ExposureRouter:
    """Select a compact slate from typed candidates."""

    def plan(
        self,
        state: RuntimeState,
        *,
        candidates: list[SurfaceCandidate],
        shortlisted: list[SurfaceCandidate],
        online_eval: dict | None = None,
    ) -> ExposurePlan:
        grouped: dict[str, list[SurfaceCandidate]] = defaultdict(list)
        for candidate in shortlisted:
            grouped[candidate.surface].append(candidate)

        selected: list[SurfaceCandidate] = []
        for surface, budget in _SURFACE_BUDGETS.items():
            ranked = sorted(
                grouped.get(surface, []),
                key=lambda item: (-(item.online_eval_score if item.online_eval_score is not None else item.score), item.item_key),
            )
            selected.extend(ranked[:budget])

        return ExposurePlan(
            state=state,
            candidates=candidates,
            shortlisted_items=shortlisted,
            selected_items=selected,
            online_eval=online_eval or {},
        )
