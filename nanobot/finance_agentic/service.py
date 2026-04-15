"""Finance agentic service and off-policy reward pipeline for nanobot."""

from __future__ import annotations

import json
import hashlib
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
    SubagentCritique,
    SubagentTrace,
    SubagentWorklog,
    task_from_dict,
    to_dict,
)
from nanobot.finance_agentic.memory import PrivateFinanceMemory, SharedFinanceMemory
from nanobot.personalization.store import PersonalizationStore
from nanobot.agent.subagent import SubagentManager
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


def _digest_text(payload: Any) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _shorten(text: str, limit: int = 160) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _default_worklog(trace: SubagentTrace) -> SubagentWorklog:
    return SubagentWorklog(
        round_id=trace.round_id,
        agent_name=trace.agent_name,
        task_id=trace.task_id,
        status=trace.status,
        input_summary=f"Prompt digest {trace.prompt_digest}",
        output_summary=f"Result digest {trace.result_digest}",
        public_contribution=f"{trace.agent_name} contributed to the round output.",
        open_issues=[],
    )


def _default_critique(trace: SubagentTrace, should_refine: bool) -> SubagentCritique:
    return SubagentCritique(
        round_id=trace.round_id,
        agent_name=trace.agent_name,
        task_id=trace.task_id,
        work_quality=0.5,
        evidence_quality=0.5,
        responsiveness_to_critique=0.5,
        summary=_shorten(f"{trace.agent_name} completed work with status {trace.status}."),
        strengths=[],
        weaknesses=[],
        action_items=[],
        should_refine=should_refine,
    )


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


def render_episode_log(episode: FinanceEpisode) -> str:
    final = episode.final_asset_output
    critic = episode.final_critic_review
    convergence = episode.final_convergence_report
    lines = [
        f"# Finance Episode {episode.episode_id}",
        "",
        "## Overview",
        f"- Task ID: {episode.task_id}",
        f"- Policy Version: {episode.policy_version}",
        f"- Asset: {episode.shared_memory_snapshot['event_object'].get('target_asset', 'unknown')}",
        f"- Final Direction: {final.direction.value}",
        f"- Final Confidence: {final.confidence:.2f}",
        f"- Critic Verdict: {critic.verdict.value}",
        f"- Stop Reason: {convergence.stop_reason or 'n/a'}",
        "",
    ]
    for round_record in episode.rounds:
        lines.extend(
            [
                f"## Round {round_record.round_id}",
                f"- Active Agents: {', '.join(round_record.active_agents) if round_record.active_agents else 'n/a'}",
                f"- Critic Verdict: {round_record.critic_review.verdict.value}",
                f"- Convergence Score: {round_record.convergence_report.convergence_score:.2f}",
                f"- Stop Flag: {round_record.convergence_report.should_stop}",
                "",
                "### Subagent Traces",
            ]
        )
        for trace in round_record.subagent_traces:
            lines.extend(
                [
                    f"- {trace.agent_name} [{trace.task_id}]",
                    f"  Status: {trace.status}",
                    f"  Prompt Digest: {trace.prompt_digest}",
                    f"  Result Digest: {trace.result_digest}",
                ]
            )
        lines.append("")
        lines.append("### Roundtable")
        for message in round_record.roundtable_messages:
            lines.extend(
                [
                    f"- {message.speaker}: {message.claim}",
                    f"  Confidence: {message.confidence:.2f}",
                    f"  Evidence: {', '.join(message.evidence) if message.evidence else 'n/a'}",
                    f"  Objections: {', '.join(message.objection_to_others) if message.objection_to_others else 'n/a'}",
                ]
            )
        lines.append("")
        lines.append("### Critic Worklogs")
        for worklog in round_record.critic_review.subagent_worklogs:
            lines.extend(
                [
                    f"- {worklog.agent_name} [{worklog.task_id}]",
                    f"  Status: {worklog.status}",
                    f"  Input: {worklog.input_summary}",
                    f"  Output: {worklog.output_summary}",
                    f"  Contribution: {worklog.public_contribution}",
                    f"  Open Issues: {', '.join(worklog.open_issues) if worklog.open_issues else 'none'}",
                ]
            )
        lines.append("")
        lines.append("### Critic Critiques")
        for critique in round_record.critic_review.subagent_critiques:
            lines.extend(
                [
                    f"- {critique.agent_name} [{critique.task_id}]",
                    f"  Summary: {critique.summary}",
                    f"  Scores: work={critique.work_quality:.2f}, evidence={critique.evidence_quality:.2f}, responsiveness={critique.responsiveness_to_critique:.2f}",
                    f"  Strengths: {', '.join(critique.strengths) if critique.strengths else 'none'}",
                    f"  Weaknesses: {', '.join(critique.weaknesses) if critique.weaknesses else 'none'}",
                    f"  Action Items: {', '.join(critique.action_items) if critique.action_items else 'none'}",
                    f"  Should Refine: {critique.should_refine}",
                ]
            )
        lines.append("")
        lines.append("### Critique Packets")
        for packet in round_record.critic_review.critique_packets:
            lines.extend(
                [
                    f"- Target: {packet.target_agent}",
                    f"  Status: {packet.status} | Severity: {packet.severity}",
                    f"  Issues: {', '.join(packet.issues) if packet.issues else 'none'}",
                    f"  Repairs: {', '.join(packet.repair_instructions) if packet.repair_instructions else 'none'}",
                ]
            )
        if not round_record.critic_review.critique_packets:
            lines.append("- none")
        lines.append("")
    lines.extend(
        [
            "## Final Conclusion",
            f"- Direction: {final.direction.value}",
            f"- Confidence: {final.confidence:.2f}",
            f"- Rationale: {final.rationale}",
        ]
    )
    return "\n".join(lines)


class FinanceAgenticService:
    """Dynamic finance multi-agent orchestration backed by a nanobot provider."""

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        workspace: Path,
        max_rounds: int = 3,
        subagents: SubagentManager | None = None,
    ):
        self.provider = provider
        self.model = model
        self.workspace = workspace
        self.max_rounds = max_rounds
        self.subagents = subagents
        self.memory = PrivateFinanceMemory(workspace)
        self.root = ensure_dir(workspace / "finance_agentic")
        self.episodes_dir = ensure_dir(self.root / "episodes")
        self.feedback_dir = ensure_dir(self.root / "feedback")
        self.outcomes_dir = ensure_dir(self.root / "outcomes")
        self.reward_scores_dir = ensure_dir(self.root / "reward_scores")

    async def _call_agent_json(
        self,
        role: str,
        instruction: str,
        payload: dict[str, Any],
        *,
        round_id: int,
        session_key: str | None,
    ) -> tuple[dict[str, Any], SubagentTrace]:
        prompt = "\n".join(
            [
                f"You are the {role} in a finance multi-agent system.",
                "Return only one valid JSON object and no prose outside JSON.",
                instruction,
                json.dumps(payload, ensure_ascii=False),
            ]
        )
        if self.subagents is None:
            response = await self.provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": f"You are the {role} in a finance multi-agent system.\nReturn only one valid JSON object and no prose outside JSON.\n{instruction}"},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                model=self.model,
                max_tokens=1200,
                temperature=0.2,
            )
            raw_result = response.content or "{}"
            trace = SubagentTrace(
                round_id=round_id,
                agent_name=role,
                task_id=f"inline-{role}-{round_id}",
                label=role,
                status="ok",
                prompt_digest=_digest_text(prompt),
                result_digest=_digest_text(raw_result),
            )
        else:
            executed = await self.subagents.run_and_wait(
                task=prompt,
                label=role,
                session_key=session_key,
            )
            raw_result = str(executed.get("result") or "{}")
            trace = SubagentTrace(
                round_id=round_id,
                agent_name=role,
                task_id=str(executed.get("task_id") or ""),
                label=str(executed.get("label") or role),
                status=str(executed.get("status") or "error"),
                prompt_digest=_digest_text(prompt),
                result_digest=_digest_text(raw_result),
            )
        parsed = json_repair.loads(raw_result)
        if not isinstance(parsed, dict):
            raise ValueError(f"{role} returned non-object JSON")
        return parsed, trace

    async def _news_step(
        self,
        task: FinanceTask,
        critique: CritiquePacket | None = None,
        *,
        round_id: int,
        session_key: str | None,
    ) -> tuple[EventSummary, SubagentTrace]:
        docs = self.memory.retrieve("news", [task.target_asset, *[item.headline for item in task.event_news]])
        payload = {
            "task": to_dict(task),
            "private_memory": docs,
            "critique_packet": None if critique is None else to_dict(critique),
        }
        result, trace = await self._call_agent_json(
            "news_agent",
            (
                "Produce keys: event_title, event_type, abstract, avg_sentiment, importance_score, "
                "supporting_news_ids, entities, evidence_bullets."
            ),
            payload,
            round_id=round_id,
            session_key=session_key,
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
        ), trace

    async def _asset_step(
        self,
        task: FinanceTask,
        news: EventSummary,
        risk: RiskAssessment | None = None,
        critique: CritiquePacket | None = None,
        *,
        round_id: int,
        session_key: str | None,
    ) -> tuple[AssetPrediction, SubagentTrace]:
        docs = self.memory.retrieve("asset", [task.target_asset, news.event_type, *news.entities])
        payload = {
            "task": to_dict(task),
            "news_output": to_dict(news),
            "risk_output": None if risk is None else to_dict(risk),
            "private_memory": docs,
            "critique_packet": None if critique is None else to_dict(critique),
        }
        result, trace = await self._call_agent_json(
            "asset_agent",
            "Produce keys: direction, confidence, rationale, evidence_ids, cited_memory_ids.",
            payload,
            round_id=round_id,
            session_key=session_key,
        )
        direction = str(result.get("direction", "neutral")).lower()
        return AssetPrediction(
            direction=Direction(direction if direction in {"up", "down", "neutral"} else "neutral"),
            confidence=_clamp(float(result.get("confidence", 0.5))),
            rationale=str(result.get("rationale") or "No rationale provided."),
            evidence_ids=[str(x) for x in result.get("evidence_ids", news.supporting_news_ids[:3])],
            cited_memory_ids=[str(x) for x in result.get("cited_memory_ids", [doc.get("doc_id", "") for doc in docs[:2]]) if x],
        ), trace

    async def _risk_step(
        self,
        task: FinanceTask,
        news: EventSummary,
        asset: AssetPrediction,
        critique: CritiquePacket | None = None,
        *,
        round_id: int,
        session_key: str | None,
    ) -> tuple[RiskAssessment, SubagentTrace]:
        docs = self.memory.retrieve("risk", [task.target_asset, news.event_type, "volatility"])
        payload = {
            "task": to_dict(task),
            "news_output": to_dict(news),
            "asset_output": to_dict(asset),
            "private_memory": docs,
            "critique_packet": None if critique is None else to_dict(critique),
        }
        result, trace = await self._call_agent_json(
            "risk_agent",
            "Produce keys: risk_level, objections, suggested_direction, confidence_penalty.",
            payload,
            round_id=round_id,
            session_key=session_key,
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
        ), trace

    async def _critic_step(
        self,
        round_id: int,
        task: FinanceTask,
        news: EventSummary,
        asset: AssetPrediction,
        risk: RiskAssessment,
        previous_asset: AssetPrediction | None,
        subagent_traces: list[SubagentTrace],
        roundtable_messages: list[RoundtableMessage],
        *,
        session_key: str | None,
    ) -> tuple[CriticReview, SubagentTrace]:
        docs = self.memory.retrieve("critic", [task.target_asset, "critic", "convergence"])
        payload = {
            "round_id": round_id,
            "task": to_dict(task),
            "news_output": to_dict(news),
            "asset_output": to_dict(asset),
            "risk_output": to_dict(risk),
            "previous_asset_output": None if previous_asset is None else to_dict(previous_asset),
            "subagent_traces": [to_dict(item) for item in subagent_traces],
            "roundtable_messages": [to_dict(item) for item in roundtable_messages],
            "private_memory": docs,
        }
        result, trace = await self._call_agent_json(
            "critic_agent",
            (
                "Produce keys: direction_quality, evidence_quality, risk_handling, revision_quality, "
                "format_compliance, final_score, verdict, blocking_issues_count, subagent_worklogs, "
                "subagent_critiques, critique_packets, notes. "
                "Each subagent_worklog needs: agent_name, task_id, status, input_summary, output_summary, "
                "public_contribution, open_issues. "
                "Each subagent_critique needs: agent_name, task_id, work_quality, evidence_quality, "
                "responsiveness_to_critique, summary, strengths, weaknesses, action_items, should_refine. "
                "Each critique packet needs target_agent, status, severity, issues, repair_instructions, score."
            ),
            payload,
            round_id=round_id,
            session_key=session_key,
        )
        worklogs: list[SubagentWorklog] = []
        for item in result.get("subagent_worklogs", []):
            if not isinstance(item, dict):
                continue
            worklogs.append(
                SubagentWorklog(
                    round_id=round_id,
                    agent_name=str(item.get("agent_name") or ""),
                    task_id=str(item.get("task_id") or ""),
                    status=str(item.get("status") or "unknown"),
                    input_summary=str(item.get("input_summary") or ""),
                    output_summary=str(item.get("output_summary") or ""),
                    public_contribution=str(item.get("public_contribution") or ""),
                    open_issues=[str(x) for x in item.get("open_issues", [])],
                )
            )
        critiques: list[SubagentCritique] = []
        for item in result.get("subagent_critiques", []):
            if not isinstance(item, dict):
                continue
            critiques.append(
                SubagentCritique(
                    round_id=round_id,
                    agent_name=str(item.get("agent_name") or ""),
                    task_id=str(item.get("task_id") or ""),
                    work_quality=_clamp(float(item.get("work_quality", 0.5))),
                    evidence_quality=_clamp(float(item.get("evidence_quality", 0.5))),
                    responsiveness_to_critique=_clamp(float(item.get("responsiveness_to_critique", 0.5))),
                    summary=str(item.get("summary") or ""),
                    strengths=[str(x) for x in item.get("strengths", [])],
                    weaknesses=[str(x) for x in item.get("weaknesses", [])],
                    action_items=[str(x) for x in item.get("action_items", [])],
                    should_refine=bool(item.get("should_refine", False)),
                )
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
        worklog_index = {item.agent_name: item for item in worklogs}
        critique_index = {item.agent_name: item for item in critiques}
        targeted_agents = {packet.target_agent for packet in packets}
        for item in subagent_traces:
            if item.agent_name not in worklog_index:
                worklogs.append(_default_worklog(item))
            if item.agent_name not in critique_index:
                critiques.append(_default_critique(item, item.agent_name in targeted_agents))
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
            subagent_worklogs=worklogs,
            subagent_critiques=critiques,
            critique_packets=packets,
            notes=[str(x) for x in result.get("notes", [])],
        ), trace

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

    async def analyze(self, task: FinanceTask, session_key: str | None = None) -> FinanceEpisode:
        news, news_trace = await self._news_step(task, round_id=0, session_key=session_key)
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
        asset, asset_trace = await self._asset_step(task, news, round_id=0, session_key=session_key)
        risk, risk_trace = await self._risk_step(task, news, asset, round_id=0, session_key=session_key)

        rounds: list[RoundRecord] = []
        previous_asset: AssetPrediction | None = None
        previous_critic: CriticReview | None = None
        active_agents = ["news", "asset", "risk"]
        pending_traces: list[SubagentTrace] = [news_trace, asset_trace, risk_trace]

        for round_id in range(1, self.max_rounds + 1):
            messages = self._build_roundtable_messages(round_id, news, asset, risk, active_agents)
            shared.add_roundtable_messages(messages)
            current_subagent_traces = list(pending_traces)
            critic, critic_trace = await self._critic_step(
                round_id,
                task,
                news,
                asset,
                risk,
                previous_asset,
                current_subagent_traces,
                messages,
                session_key=session_key,
            )
            previous_open_issues = list(shared.open_issues)
            current_issues = _flatten_issues(critic.critique_packets)
            shared.update_open_issues(current_issues)
            shared.resolve_issues([issue for issue in previous_open_issues if issue not in current_issues])
            convergence = self._build_convergence(round_id, asset, risk, critic, previous_asset, previous_critic)
            round_traces = current_subagent_traces + [critic_trace]
            rounds.append(
                RoundRecord(
                    round_id=round_id,
                    active_agents=list(active_agents),
                    subagent_traces=round_traces,
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
            pending_traces = []
            if "news" in packets:
                news, trace = await self._news_step(task, packets["news"], round_id=round_id, session_key=session_key)
                shared.add_public_evidence(news.evidence_bullets)
                next_active_agents.append("news")
                pending_traces.append(trace)
            if "asset" in packets:
                asset, trace = await self._asset_step(task, news, risk, packets["asset"], round_id=round_id, session_key=session_key)
                next_active_agents.append("asset")
                pending_traces.append(trace)
            if "risk" in packets:
                risk, trace = await self._risk_step(task, news, asset, packets["risk"], round_id=round_id, session_key=session_key)
                next_active_agents.append("risk")
                pending_traces.append(trace)
            if "news" in packets and "asset" not in packets:
                asset, trace = await self._asset_step(task, news, risk, round_id=round_id, session_key=session_key)
                next_active_agents.append("asset")
                pending_traces.append(trace)
            if "asset" in packets or "news" in packets:
                risk, trace = await self._risk_step(task, news, asset, round_id=round_id, session_key=session_key)
                if "risk" not in next_active_agents:
                    next_active_agents.append("risk")
                pending_traces.append(trace)
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
        log_path = self.episodes_dir / f"{episode.episode_id}.log.md"
        log_path.write_text(render_episode_log(episode), encoding="utf-8")
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
