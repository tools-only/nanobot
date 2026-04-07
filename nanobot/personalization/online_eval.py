"""Lightweight online reward comparison over a small shortlist."""

from __future__ import annotations

from collections import defaultdict

from nanobot.personalization.contracts import RuntimeState, SurfaceCandidate

_SURFACE_OFFSETS = {
    "context_evidence": 0.10,
    "capability_exposure": 0.06,
    "acquisition_policy": 0.04,
    "interaction_hint": 0.05,
    "knowledge_exposure": 0.03,
}


class LightweightOnlineRewardEvaluator:
    """Score only shortlisted items, not the full combinatorial space."""

    def evaluate(
        self,
        *,
        state: RuntimeState,
        shortlisted: list[SurfaceCandidate],
    ) -> tuple[list[SurfaceCandidate], dict]:
        lowered = state.current_message.lower()
        comparisons: dict[str, list[dict[str, float | str]]] = defaultdict(list)
        evaluated: list[SurfaceCandidate] = []

        for candidate in shortlisted:
            score = float(candidate.score)
            score += _SURFACE_OFFSETS.get(candidate.surface, 0.0)

            if candidate.surface == "context_evidence" and state.profile and state.profile.summary:
                score += 0.05
            if candidate.surface == "capability_exposure" and any(
                token in lowered for token in ("search", "weather", "latest", "schedule", "ticket")
            ):
                score += 0.05
            if candidate.surface == "acquisition_policy" and any(
                token in lowered for token in ("latest", "today", "news", "price", "weather")
            ):
                score += 0.08
            if candidate.surface == "interaction_hint" and state.profile and state.profile.topic_counts:
                score += 0.04

            candidate.online_eval_score = round(score, 4)
            evaluated.append(candidate)
            comparisons[candidate.surface].append({
                "candidate_id": candidate.candidate_id,
                "item_key": candidate.item_key,
                "score": candidate.online_eval_score,
            })

        return evaluated, {
            "mode": "lightweight_shortlist_compare",
            "shortlist_count": len(shortlisted),
            "comparisons": dict(comparisons),
        }
