"""Typed contracts for finance agentic orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class CriticVerdict(str, Enum):
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"


@dataclass(slots=True)
class NewsItem:
    news_id: str
    headline: str
    source: str
    published_at: str
    summary: str
    sentiment_score: float = 0.0
    importance: float = 0.5
    entities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FinanceTask:
    task_id: str
    as_of_time: str
    event_news: list[NewsItem]
    market_snapshot: dict[str, float]
    target_asset: str
    outcome_label_t3: str | None = None


@dataclass(slots=True)
class EventSummary:
    event_title: str
    event_type: str
    abstract: str
    avg_sentiment: float
    importance_score: float
    supporting_news_ids: list[str]
    entities: list[str]
    evidence_bullets: list[str]


@dataclass(slots=True)
class AssetPrediction:
    direction: Direction
    confidence: float
    rationale: str
    evidence_ids: list[str]
    cited_memory_ids: list[str]


@dataclass(slots=True)
class RiskAssessment:
    risk_level: float
    objections: list[str]
    suggested_direction: Direction | None
    confidence_penalty: float


@dataclass(slots=True)
class RoundtableMessage:
    round_id: int
    speaker: str
    claim: str
    evidence: list[str]
    objection_to_others: list[str]
    confidence: float
    what_would_change_my_mind: str


@dataclass(slots=True)
class SubagentTrace:
    round_id: int
    agent_name: str
    task_id: str
    label: str
    status: str
    prompt_digest: str
    result_digest: str


@dataclass(slots=True)
class CritiquePacket:
    round_id: int
    target_agent: str
    status: str
    severity: str
    issues: list[str]
    repair_instructions: list[str]
    score: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class CriticReview:
    round_id: int
    direction_quality: float
    evidence_quality: float
    risk_handling: float
    revision_quality: float
    format_compliance: float
    final_score: float
    verdict: CriticVerdict
    blocking_issues_count: int
    critique_packets: list[CritiquePacket] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConvergenceReport:
    round_id: int
    conclusion_stability: float
    disagreement_score: float
    information_gain: float
    blocking_issues_count: int
    oscillation_detected: bool
    convergence_score: float
    should_stop: bool
    stop_reason: str


@dataclass(slots=True)
class RoundRecord:
    round_id: int
    active_agents: list[str]
    subagent_traces: list[SubagentTrace]
    roundtable_messages: list[RoundtableMessage]
    critic_review: CriticReview
    convergence_report: ConvergenceReport
    news_output: EventSummary
    asset_output: AssetPrediction
    risk_output: RiskAssessment


@dataclass(slots=True)
class RewardModelScore:
    preference_score: float
    outcome_alignment_score: float
    human_alignment_score: float
    composite_reward: float
    reasoning_summary: str
    model_version: str


@dataclass(slots=True)
class FinanceEpisode:
    episode_id: str
    task_id: str
    policy_version: str
    shared_memory_snapshot: dict[str, Any]
    rounds: list[RoundRecord]
    final_news_output: EventSummary
    final_asset_output: AssetPrediction
    final_risk_output: RiskAssessment
    final_critic_review: CriticReview
    final_convergence_report: ConvergenceReport
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    reward_model_score: RewardModelScore | None = None


def to_dict(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    return value


def task_from_dict(payload: dict[str, Any]) -> FinanceTask:
    items = [NewsItem(**item) for item in payload["event_news"]]
    return FinanceTask(
        task_id=payload["task_id"],
        as_of_time=payload["as_of_time"],
        event_news=items,
        market_snapshot=payload.get("market_snapshot", {}),
        target_asset=payload.get("target_asset", "unknown"),
        outcome_label_t3=payload.get("outcome_label_t3"),
    )
