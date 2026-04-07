"""Typed candidate generation for personalization surfaces."""

from __future__ import annotations

from nanobot.personalization.contracts import RuntimeState, SurfaceCandidate
from nanobot.personalization.providers import ContextVariableRegistry
from nanobot.personalization.score_tables import ScoreTables


class CandidateGenerators:
    """Generate a small typed candidate set without an extra model."""

    def __init__(self, scores: ScoreTables, *, providers: ContextVariableRegistry | None = None):
        self.scores = scores
        self.providers = providers or ContextVariableRegistry()

    def generate(self, state: RuntimeState) -> list[SurfaceCandidate]:
        candidates: list[SurfaceCandidate] = []
        candidates.extend(self._context_candidates(state))
        candidates.extend(self._capability_candidates(state))
        candidates.extend(self._acquisition_candidates(state))
        candidates.extend(self._interaction_candidates(state))
        candidates.extend(self.providers.generate(state))
        return self._deduplicate(candidates)

    @staticmethod
    def _deduplicate(candidates: list[SurfaceCandidate]) -> list[SurfaceCandidate]:
        deduped: dict[str, SurfaceCandidate] = {}
        for candidate in candidates:
            current = deduped.get(candidate.candidate_id)
            if current is None or candidate.score > current.score:
                deduped[candidate.candidate_id] = candidate
        return list(deduped.values())

    def _context_candidates(self, state: RuntimeState) -> list[SurfaceCandidate]:
        out: list[SurfaceCandidate] = []
        if state.profile and state.profile.summary:
            out.append(SurfaceCandidate(
                candidate_id="profile-summary",
                surface="context_evidence",
                slot="profile_summary",
                item_key="profile_summary",
                title="Profile Summary",
                summary=state.profile.summary,
                score=0.4 + self.scores.get_recall_prior(
                    user_key=state.user_key,
                    item_key="profile_summary",
                    surface="context_evidence",
                ),
                reasons=["profile_available"],
            ))

        if state.recent_user_messages:
            recent = " | ".join(state.recent_user_messages[-2:])
            out.append(SurfaceCandidate(
                candidate_id="recent-memory",
                surface="context_evidence",
                slot="recent_memory",
                item_key="recent_memory",
                title="Recent User Context",
                summary=f"Relevant recent user context: {recent[:280]}",
                score=0.3 + self.scores.get_recall_prior(
                    user_key=state.user_key,
                    item_key="recent_memory",
                    surface="context_evidence",
                ),
                reasons=["recent_history_available"],
            ))
        return out

    def _capability_candidates(self, state: RuntimeState) -> list[SurfaceCandidate]:
        text = state.current_message.lower()
        out: list[SurfaceCandidate] = []
        if any(keyword in text for keyword in ("schedule", "calendar", "remind", "holiday", "tomorrow")):
            out.append(SurfaceCandidate(
                candidate_id="cap-cron",
                surface="capability_exposure",
                slot="capability_hint",
                item_key="cron_tool",
                title="Scheduling Capability Hint",
                summary="If scheduling, reminder, or proactive follow-up would help, prefer the cron tool.",
                score=0.2 + self.scores.get_recall_prior(
                    user_key=state.user_key,
                    item_key="cron_tool",
                    surface="capability_exposure",
                ),
                reasons=["schedule_intent"],
            ))
        if any(keyword in text for keyword in ("weather", "search", "news", "latest")):
            out.append(SurfaceCandidate(
                candidate_id="cap-web",
                surface="capability_exposure",
                slot="capability_hint",
                item_key="web_tools",
                title="Web Capability Hint",
                summary="If freshness matters, prefer web search/fetch rather than relying on stale memory.",
                score=0.2 + self.scores.get_recall_prior(
                    user_key=state.user_key,
                    item_key="web_tools",
                    surface="capability_exposure",
                ),
                reasons=["freshness_intent"],
            ))
        return out

    def _acquisition_candidates(self, state: RuntimeState) -> list[SurfaceCandidate]:
        text = state.current_message.lower()
        out: list[SurfaceCandidate] = []
        if any(keyword in text for keyword in ("latest", "today", "news", "weather", "price")):
            out.append(SurfaceCandidate(
                candidate_id="search-world",
                surface="acquisition_policy",
                slot="search_policy",
                item_key="world_search",
                title="World Search Policy",
                summary="Prefer time-sensitive external search if the answer may have changed recently.",
                score=0.25 + self.scores.get_recall_prior(
                    user_key=state.user_key,
                    item_key="world_search",
                    surface="acquisition_policy",
                ),
                reasons=["time_sensitive_query"],
            ))
        return out

    def _interaction_candidates(self, state: RuntimeState) -> list[SurfaceCandidate]:
        out: list[SurfaceCandidate] = []
        if state.profile and state.profile.summary:
            out.append(SurfaceCandidate(
                candidate_id="hint-light-personalize",
                surface="interaction_hint",
                slot="interaction_policy",
                item_key="light_personalize",
                title="Light Personalization Hint",
                summary="Use known user preferences only when they clearly reduce effort; do not overstate inference.",
                score=0.15 + self.scores.get_recall_prior(
                    user_key=state.user_key,
                    item_key="light_personalize",
                    surface="interaction_hint",
                ),
                reasons=["profile_available"],
            ))
        return out
