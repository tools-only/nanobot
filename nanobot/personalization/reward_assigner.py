"""Asynchronous reward-assignment request generation."""

from __future__ import annotations

from uuid import uuid4

from nanobot.personalization.contracts import ExposurePlan, RewardAssignmentRequest


class RewardAssigner:
    """Build a pending reward-assignment task for an external or future judge."""

    def build_request(
        self,
        *,
        plan: ExposurePlan,
        final_content: str | None,
        feedback_signals: dict,
        proxy_metrics: dict,
        trace: list[dict],
    ) -> RewardAssignmentRequest:
        return RewardAssignmentRequest(
            turn_id=str(uuid4()),
            user_key=plan.state.user_key,
            session_key=plan.state.session_key,
            status="pending",
            candidate_items=[item.to_dict() for item in plan.candidates],
            shortlisted_items=[item.to_dict() for item in plan.shortlisted_items],
            selected_items=[item.to_dict() for item in plan.selected_items],
            state=plan.state.to_dict(),
            feedback_signals=feedback_signals,
            proxy_metrics=proxy_metrics,
            trace=trace,
            online_eval=dict(plan.online_eval),
            final_content=final_content,
        )
