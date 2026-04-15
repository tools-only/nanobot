"""Finance agentic service and off-policy reward pipeline for nanobot."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import json_repair
except ImportError:  # pragma: no cover - fallback for minimal runtime environments
    class _JsonRepairModule:
        @staticmethod
        def loads(payload: str) -> Any:
            return json.loads(payload)

    json_repair = _JsonRepairModule()

from nanobot.finance_agentic.contracts import (
    AssetPrediction,
    ConvergenceReport,
    CriticReview,
    CriticVerdict,
    CritiquePacket,
    Direction,
    EventSummary,
    FinanceEpisode,
    FinanceTask,
    NewsItem,
    RewardModelScore,
    RiskAssessment,
    RoundRecord,
    RoundtableMessage,
    task_from_dict,
    to_dict,
)
from nanobot.finance_agentic.memory import PrivateFinanceMemory, SharedFinanceMemory
from nanobot.personalization.store import PersonalizationStore
from nanobot.providers.base import LLMProvider
from nanobot.utils.helpers import ensure_dir, safe_filename, timestamp


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _flatten_issues(packets: list[CritiquePacket]) -> list[str]:
    issues: list[str] = []
    for packet in packets:
        for issue in packet.issues:
            if issue not in issues:
                issues.append(issue)
    return issues


def parse_finance_task_argument(raw: str, workspace: Path) -> FinanceTask:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Usage: /finance <json file path | json payload | plain text thesis>")
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = workspace / text
    if candidate.exists() and candidate.is_file():
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        return task_from_dict(payload)
    if text.startswith("{"):
        return task_from_dict(json_repair.loads(text))
    return FinanceTask(
        task_id=f"chat-{uuid4().hex[:8]}",
        as_of_time=datetime.now(UTC).isoformat(),
        event_news=[
            NewsItem(
                news_id="inline-1",
                headline=text[:80],
                source="user",
                published_at=datetime.now(UTC).isoformat(),
                summary=text,
                sentiment_score=0.0,
                importance=0.5,
                entities=[],
                tags=["inline_prompt"],
            )
        ],
        market_snapshot={"market_return": 0.0, "volume_shock": 0.0, "volatility": 0.2, "risk_off": 0.2},
        target_asset="unspecified",
    )


def format_episode_summary(episode: FinanceEpisode) -> str:
    final = episode.final_asset_output
    critic = episode.final_critic_review
    convergence = episode.final_convergence_report
    risk = episode.final_risk_output
    lines = [
        f"Asset: {episode.shared_memory_snapshot['event_object'].get('target_asset', 'unknown')}",
        f"Direction: {final.direction.value}",
        f"Confidence: {final.confidence:.2f}",
        f"Rounds: {len(episode.rounds)}",
        f"Critic verdict: {critic.verdict.value}",
        f"Stop reason: {convergence.stop_reason or 'n/a'}",
        f"Rationale: {final.rationale}",
    ]
    if risk.objections:
        lines.append(f"Top risk: {risk.objections[0]}")
    return "\n".join(lines)


class FinanceAgenticService:
    """Dynamic finance multi-agent orchestration backed by a nanobot provider."""

    def __init__(self, provider: LLMProvider, model: str, workspace: Path, max_rounds: int = 3):
        self.provider = provider
        self.model = model
        self.workspace = workspace
        self.max_rounds = max_rounds
        self.memory = PrivateFinanceMemory(workspace)
        self.root = ensure_dir(workspace / "finance_agentic")
        self.episodes_dir = ensure_dir(self.root / "episodes")
        self.feedback_dir = ensure_dir(self.root / "feedback")
        self.outcomes_dir = ensure_dir(self.root / "outcomes")
        self.reward_scores_dir = ensure_dir(self.root / "reward_scores")

    async def _call_json(self, role: str, instruction: str, payload: dict[str, Any]) -> dict[str, Any]:
        system_prompt = (
            f"You are the {role} in a finance multi-agent system.\n"
            "Return only one valid JSON object and no prose outside JSON.\n"
            f"{instruction}"
        )
        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            model=self.model,
            max_tokens=1200,
            temperature=0.2,
        )
        parsed = json_repair.loads(response.content or "{}")
        if not isinstance(parsed, dict):
            raise ValueError(f"{role} returned non-object JSON")
        return parsed

    async def _news_step(self, task: FinanceTask, critique: CritiquePacket | None = None) -> EventSummary:
        docs = self.memory.retrieve("news", [task.target_asset, *[item.headline for item in task.event_news]])
        payload = {
            "task": to_dict(task),
            "private_memory": docs,
            "critique_packet": None if critique is None else to_dict(critique),
        }
        result = await self._call_json(
            "news_agent",
            (
                "Produce keys: event_title, event_type, abstract, avg_sentiment, importance_score, "
                "supporting_news_ids, entities, evidence_bullets."
            ),
            payload,
        )
        return EventSummary(
            event_title=str(result.get("event_title") or task.event_news[0].headline),
            event_type=str(result.get("event_type") or "macro_event"),
            abstract=str(result.get("abstract") or task.event_news[0].summary),
            avg_sentiment=float(result.get("avg_sentiment", 0.0)),
            importance_score=_clamp(float(result.get("importance_score", 0.5))),
            supporting_news_ids=[str(x) for x in result.get("supporting_news_ids", [item.news_id for item in task.event_news])],
            entities=[str(x) for x in result.get("entities", [])],
            evidence_bullets=[str(x) for x in result.get("evidence_bullets", [])][:5],
        )

    async def _asset_step(
        self,
        task: FinanceTask,
        news: EventSummary,
        risk: RiskAssessment | None = None,
        critique: CritiquePacket | None = None,
    ) -> AssetPrediction:
        docs = self.memory.retrieve("asset", [task.target_asset, news.event_type, *news.entities])
        payload = {
            "task": to_dict(task),
            "news_output": to_dict(news),
            "risk_output": None if risk is None else to_dict(risk),
            "private_memory": docs,
            "critique_packet": None if critique is None else to_dict(critique),
        }
        result = await self._call_json(
            "asset_agent",
            "Produce keys: direction, confidence, rationale, evidence_ids, cited_memory_ids.",
            payload,
        )
        direction = str(result.get("direction", "neutral")).lower()
        return AssetPrediction(
            direction=Direction(direction if direction in {"up", "down", "neutral"} else "neutral"),
            confidence=_clamp(float(result.get("confidence", 0.5))),
            rationale=str(result.get("rationale") or "No rationale provided."),
            evidence_ids=[str(x) for x in result.get("evidence_ids", news.supporting_news_ids[:3])],
            cited_memory_ids=[str(x) for x in result.get("cited_memory_ids", [doc.get("doc_id", "") for doc in docs[:2]]) if x],
        )

    async def _risk_step(
        self,
        task: FinanceTask,
        news: EventSummary,
        asset: AssetPrediction,
        critique: CritiquePacket | None = None,
    ) -> RiskAssessment:
        docs = self.memory.retrieve("risk", [task.target_asset, news.event_type, "volatility"])
        payload = {
            "task": to_dict(task),
            "news_output": to_dict(news),
            "asset_output": to_dict(asset),
            "private_memory": docs,
            "critique_packet": None if critique is None else to_dict(critique),
        }
        result = await self._call_json(
            "risk_agent",
            "Produce keys: risk_level, objections, suggested_direction, confidence_penalty.",
            payload,
        )
        suggested = result.get("suggested_direction")
        suggested_direction = None
        if isinstance(suggested, str) and suggested.lower() in {"up", "down", "neutral"}:
            suggested_direction = Direction(suggested.lower())
        return RiskAssessment(
            risk_level=_clamp(float(result.get("risk_level", 0.4))),
            objections=[str(x) for x in result.get("objections", [])][:5],
            suggested_direction=suggested_direction,
            confidence_penalty=_clamp(float(result.get("confidence_penalty", 0.15))),
        )

    async def _critic_step(
        self,
        round_id: int,
        task: FinanceTask,
        news: EventSummary,
        asset: AssetPrediction,
        risk: RiskAssessment,
        previous_asset: AssetPrediction | None,
    ) -> CriticReview:
        docs = self.memory.retrieve("critic", [task.target_asset, "critic", "convergence"])
        payload = {
            "round_id": round_id,
            "task": to_dict(task),
            "news_output": to_dict(news),
            "asset_output": to_dict(asset),
            "risk_output": to_dict(risk),
            "previous_asset_output": None if previous_asset is None else to_dict(previous_asset),
            "private_memory": docs,
        }
        result = await self._call_json(
            "critic_agent",
            (
                "Produce keys: direction_quality, evidence_quality, risk_handling, revision_quality, "
                "format_compliance, final_score, verdict, blocking_issues_count, critique_packets, notes. "
                "Each critique packet needs target_agent, status, severity, issues, repair_instructions, score."
            ),
            payload,
        )
        packets: list[CritiquePacket] = []
        for packet in result.get("critique_packets", []):
            if not isinstance(packet, dict):
                continue
            packets.append(
                CritiquePacket(
                    round_id=round_id,
                    target_agent=str(packet.get("target_agent") or "asset"),
                    status=str(packet.get("status") or "needs_refine"),
                    severity=str(packet.get("severity") or "medium"),
                    issues=[str(x) for x in packet.get("issues", [])],
                    repair_instructions=[str(x) for x in packet.get("repair_instructions", [])],
                    score={str(k): float(v) for k, v in dict(packet.get("score", {})).items()},
                )
            )
        verdict_raw = str(result.get("verdict", "revise")).lower()
        verdict = CriticVerdict(verdict_raw if verdict_raw in {"accept", "revise", "reject"} else "revise")
        return CriticReview(
            round_id=round_id,
            direction_quality=_clamp(float(result.get("direction_quality", 0.5))),
            evidence_quality=_clamp(float(result.get("evidence_quality", 0.5))),
            risk_handling=_clamp(float(result.get("risk_handling", 0.5))),
            revision_quality=_clamp(float(result.get("revision_quality", 0.5))),
            format_compliance=_clamp(float(result.get("format_compliance", 1.0))),
            final_score=_clamp(float(result.get("final_score", 0.5))),
            verdict=verdict,
            blocking_issues_count=int(result.get("blocking_issues_count", len(packets))),
            critique_packets=packets,
            notes=[str(x) for x in result.get("notes", [])],
        )

    def _build_roundtable_messages(
        self,
        round_id: int,
        news: EventSummary,
        asset: AssetPrediction,
        risk: RiskAssessment,
        active_agents: list[str],
    ) -> list[RoundtableMessage]:
        messages: list[RoundtableMessage] = []
        if "news" in active_agents:
            messages.append(
                RoundtableMessage(
                    round_id=round_id,
                    speaker="news",
                    claim=f"Event type {news.event_type} with weighted sentiment {news.avg_sentiment:.2f}.",
                    evidence=list(news.supporting_news_ids[:3]),
                    objection_to_others=[],
                    confidence=news.importance_score,
                    what_would_change_my_mind="Higher-quality conflicting evidence.",
                )
            )
        if "asset" in active_agents:
            messages.append(
                RoundtableMessage(
                    round_id=round_id,
                    speaker="asset",
                    claim=f"{asset.direction.value} over T+3 with confidence {asset.confidence:.2f}.",
                    evidence=list(asset.evidence_ids[:3]),
                    objection_to_others=list(risk.objections[:1]),
                    confidence=asset.confidence,
                    what_would_change_my_mind="Material conflict between event signal and market conditions.",
                )
            )
        if "risk" in active_agents:
            messages.append(
                RoundtableMessage(
                    round_id=round_id,
                    speaker="risk",
                    claim="Primary risk objections to the current thesis.",
                    evidence=[],
                    objection_to_others=list(risk.objections[:2]),
                    confidence=risk.risk_level,
                    what_would_change_my_mind="Stronger confirmation with lower volatility and fewer unresolved objections.",
                )
            )
        return messages

    def _build_convergence(
        self,
        round_id: int,
        asset: AssetPrediction,
        risk: RiskAssessment,
        critic: CriticReview,
        previous_asset: AssetPrediction | None,
        previous_critic: CriticReview | None,
    ) -> ConvergenceReport:
        if previous_asset is None:
            conclusion_stability = 0.45
            information_gain = critic.final_score
        else:
            same_direction = asset.direction == previous_asset.direction
            confidence_delta = abs(asset.confidence - previous_asset.confidence)
            conclusion_stability = 1.0 if same_direction and confidence_delta < 0.05 else max(0.0, 0.65 - confidence_delta)
            score_gain = max(0.0, critic.final_score - (previous_critic.final_score if previous_critic else 0.0))
            info_from_change = min(1.0, confidence_delta + (0.4 if not same_direction else 0.0))
            information_gain = min(1.0, score_gain + info_from_change)
        disagreement_score = 0.0
        if risk.suggested_direction and risk.suggested_direction != asset.direction:
            disagreement_score = 0.65
        elif risk.risk_level > 0.5 and asset.confidence > 0.7:
            disagreement_score = 0.4
        oscillation = previous_asset is not None and previous_asset.direction != asset.direction and previous_critic is not None and previous_critic.verdict == critic.verdict
        convergence_score = _clamp(
            0.35 * conclusion_stability
            + 0.35 * critic.final_score
            + 0.15 * (1.0 - disagreement_score)
            + 0.15 * max(0.0, 1.0 - critic.blocking_issues_count / 3)
        )
        should_stop = False
        stop_reason = ""
        if round_id >= self.max_rounds:
            should_stop = True
            stop_reason = "max_rounds"
        elif oscillation and round_id >= 2:
            should_stop = True
            stop_reason = "oscillation"
        elif information_gain < 0.03 and round_id >= 2:
            should_stop = True
            stop_reason = "low_information_gain"
        elif critic.verdict == CriticVerdict.ACCEPT and critic.blocking_issues_count == 0 and convergence_score >= 0.72:
            should_stop = True
            stop_reason = "soft_converged"
        return ConvergenceReport(
            round_id=round_id,
            conclusion_stability=round(conclusion_stability, 4),
            disagreement_score=round(disagreement_score, 4),
            information_gain=round(information_gain, 4),
            blocking_issues_count=critic.blocking_issues_count,
            oscillation_detected=oscillation,
            convergence_score=round(convergence_score, 4),
            should_stop=should_stop,
            stop_reason=stop_reason,
        )

    async def analyze(self, task: FinanceTask) -> FinanceEpisode:
        news = await self._news_step(task)
        shared = SharedFinanceMemory(
            event_object={
                "task_id": task.task_id,
                "event_title": news.event_title,
                "event_type": news.event_type,
                "target_asset": task.target_asset,
                "entities": news.entities,
            },
            market_summary=task.market_snapshot,
        )
        shared.add_public_evidence(news.evidence_bullets)
        asset = await self._asset_step(task, news)
        risk = await self._risk_step(task, news, asset)

        rounds: list[RoundRecord] = []
        previous_asset: AssetPrediction | None = None
        previous_critic: CriticReview | None = None
        active_agents = ["news", "asset", "risk"]

        for round_id in range(1, self.max_rounds + 1):
            messages = self._build_roundtable_messages(round_id, news, asset, risk, active_agents)
            shared.add_roundtable_messages(messages)
            critic = await self._critic_step(round_id, task, news, asset, risk, previous_asset)
            previous_open_issues = list(shared.open_issues)
            current_issues = _flatten_issues(critic.critique_packets)
            shared.update_open_issues(current_issues)
            shared.resolve_issues([issue for issue in previous_open_issues if issue not in current_issues])
            convergence = self._build_convergence(round_id, asset, risk, critic, previous_asset, previous_critic)
            rounds.append(
                RoundRecord(
                    round_id=round_id,
                    active_agents=list(active_agents),
                    roundtable_messages=messages,
                    critic_review=critic,
                    convergence_report=convergence,
                    news_output=news,
                    asset_output=asset,
                    risk_output=risk,
                )
            )
            if convergence.should_stop:
                break
            packets = {packet.target_agent: packet for packet in critic.critique_packets}
            next_active_agents: list[str] = []
            if "news" in packets:
                news = await self._news_step(task, packets["news"])
                shared.add_public_evidence(news.evidence_bullets)
                next_active_agents.append("news")
            if "asset" in packets:
                asset = await self._asset_step(task, news, risk, packets["asset"])
                next_active_agents.append("asset")
            if "risk" in packets:
                risk = await self._risk_step(task, news, asset, packets["risk"])
                next_active_agents.append("risk")
            if "news" in packets and "asset" not in packets:
                asset = await self._asset_step(task, news, risk)
                next_active_agents.append("asset")
            if "asset" in packets or "news" in packets:
                risk = await self._risk_step(task, news, asset)
                if "risk" not in next_active_agents:
                    next_active_agents.append("risk")
            previous_asset = asset
            previous_critic = critic
            active_agents = next_active_agents or ["asset"]

        final_round = rounds[-1]
        shared.set_final_conclusion(
            {
                "direction": final_round.asset_output.direction.value,
                "confidence": final_round.asset_output.confidence,
                "evidence_ids": final_round.asset_output.evidence_ids,
                "rounds": len(rounds),
                "stop_reason": final_round.convergence_report.stop_reason,
            }
        )
        episode = FinanceEpisode(
            episode_id=f"{safe_filename(task.task_id)}-{uuid4().hex[:8]}",
            task_id=task.task_id,
            policy_version=f"nanobot-{self.model}",
            shared_memory_snapshot=shared.snapshot(),
            rounds=rounds,
            final_news_output=final_round.news_output,
            final_asset_output=final_round.asset_output,
            final_risk_output=final_round.risk_output,
            final_critic_review=final_round.critic_review,
            final_convergence_report=final_round.convergence_report,
        )
        self.write_episode(episode)
        return episode

    def write_episode(self, episode: FinanceEpisode) -> Path:
        path = self.episodes_dir / f"{episode.episode_id}.json"
        path.write_text(json.dumps(to_dict(episode), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def _load_reward_requests_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except Exception:
                continue
    return rows


def enqueue_offpolicy_reward_requests(workspace: Path, include_scored: bool = False) -> int:
    root = ensure_dir(workspace / "finance_agentic")
    episodes_dir = ensure_dir(root / "episodes")
    reward_scores_dir = ensure_dir(root / "reward_scores")
    store = PersonalizationStore(workspace)
    existing = {
        row.get("episode_id")
        for row in _load_reward_requests_jsonl(store.reward_requests_path)
        if row.get("kind") == "finance_agentic_reward"
    }
    queued = 0
    for path in episodes_dir.glob("*.json"):
        episode_id = path.stem
        if episode_id in existing:
            continue
        if not include_scored and (reward_scores_dir / f"{episode_id}.json").exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        store.append_reward_request(
            {
                "kind": "finance_agentic_reward",
                "episode_id": episode_id,
                "task_id": payload.get("task_id"),
                "policy_version": payload.get("policy_version"),
                "status": "pending",
            }
        )
        queued += 1
    return queued


async def process_offpolicy_reward_requests(
    workspace: Path,
    provider: LLMProvider,
    model: str,
    model_version: str = "finance-reward-llm-v0",
) -> int:
    root = ensure_dir(workspace / "finance_agentic")
    episodes_dir = ensure_dir(root / "episodes")
    reward_scores_dir = ensure_dir(root / "reward_scores")
    feedback_dir = ensure_dir(root / "feedback")
    outcomes_dir = ensure_dir(root / "outcomes")
    store = PersonalizationStore(workspace)
    processed = 0
    for row in _load_reward_requests_jsonl(store.reward_requests_path):
        if row.get("kind") != "finance_agentic_reward":
            continue
        episode_id = str(row.get("episode_id") or "")
        if not episode_id or (reward_scores_dir / f"{episode_id}.json").exists():
            continue
        episode_path = episodes_dir / f"{episode_id}.json"
        if not episode_path.exists():
            continue
        payload = json.loads(episode_path.read_text(encoding="utf-8"))
        feedback = None
        outcome = None
        feedback_path = feedback_dir / f"{episode_id}.json"
        outcome_path = outcomes_dir / f"{episode_id}.json"
        if feedback_path.exists():
            feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
        if outcome_path.exists():
            outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        prompt_payload = {
            "episode": payload,
            "human_feedback": feedback,
            "outcome": outcome,
        }
        response = await provider.chat_with_retry(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an external reward model for finance agentic RL. "
                        "Return one JSON object with keys: preference_score, outcome_alignment_score, "
                        "human_alignment_score, composite_reward, reasoning_summary."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
            ],
            model=model,
            max_tokens=800,
            temperature=0.0,
        )
        parsed = json_repair.loads(response.content or "{}")
        score = RewardModelScore(
            preference_score=_clamp(float(parsed.get("preference_score", 0.5))),
            outcome_alignment_score=_clamp(float(parsed.get("outcome_alignment_score", 0.5))),
            human_alignment_score=_clamp(float(parsed.get("human_alignment_score", 0.5))),
            composite_reward=_clamp(float(parsed.get("composite_reward", 0.5))),
            reasoning_summary=str(parsed.get("reasoning_summary", "")),
            model_version=model_version,
        )
        (reward_scores_dir / f"{episode_id}.json").write_text(
            json.dumps(to_dict(score), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        processed += 1
    return processed
