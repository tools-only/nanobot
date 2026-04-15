from __future__ import annotations

import json
from collections import defaultdict
from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_finance
from nanobot.command.router import CommandContext
from nanobot.finance_agentic.contracts import FinanceTask, NewsItem
from nanobot.finance_agentic.service import (
    FinanceAgenticService,
    enqueue_offpolicy_reward_requests,
    process_offpolicy_reward_requests,
    render_episode_log,
)
from nanobot.personalization.store import PersonalizationStore
from nanobot.providers.base import LLMProvider, LLMResponse


def _sample_task() -> FinanceTask:
    return FinanceTask(
        task_id="tariff-apple-001",
        as_of_time="2025-01-10T12:00:00+00:00",
        event_news=[
            NewsItem(
                news_id="news-1",
                headline="US tariff plan raises concern over consumer electronics imports",
                source="wire",
                published_at="2025-01-10T11:45:00+00:00",
                summary="Tariff headlines raise concern about consumer electronics input costs and near-term sentiment.",
                sentiment_score=-0.4,
                importance=0.8,
                entities=["AAPL", "US", "China"],
                tags=["tariff", "macro"],
            )
        ],
        market_snapshot={
            "market_return": -0.01,
            "volume_shock": 0.32,
            "volatility": 0.41,
            "risk_off": 0.54,
        },
        target_asset="AAPL",
        outcome_label_t3="down",
    )


class ScriptedFinanceProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.role_counts: defaultdict[str, int] = defaultdict(int)

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    ) -> LLMResponse:
        system_prompt = str(messages[0]["content"])
        user_payload = json.loads(messages[1]["content"])
        self.calls.append(system_prompt)

        if "news_agent" in system_prompt:
            idx = self.role_counts["news"]
            self.role_counts["news"] += 1
            payload = {
                "event_title": "Tariff shock hits electronics supply chain",
                "event_type": "macro_policy",
                "abstract": "Tariff headlines pressure imported-input consumer electronics names.",
                "avg_sentiment": -0.35,
                "importance_score": 0.82,
                "supporting_news_ids": ["news-1"],
                "entities": ["AAPL", "tariffs", "consumer electronics"],
                "evidence_bullets": [
                    "Tariff headlines point to higher input-cost uncertainty.",
                    "Risk-off tape increases sensitivity to margin compression.",
                ],
            }
            if idx > 0:
                payload["evidence_bullets"].append("Refined event framing emphasizes short-horizon sentiment shock.")
            return LLMResponse(content=json.dumps(payload))

        if "asset_agent" in system_prompt:
            idx = self.role_counts["asset"]
            self.role_counts["asset"] += 1
            if idx == 0:
                payload = {
                    "direction": "down",
                    "confidence": 0.62,
                    "rationale": "Tariff shock and risk-off tone likely pressure AAPL over T+3.",
                    "evidence_ids": ["news-1"],
                    "cited_memory_ids": ["asset-default-1"],
                }
            else:
                critique = user_payload.get("critique_packet") or {}
                payload = {
                    "direction": "down",
                    "confidence": 0.56,
                    "rationale": (
                        "Downside remains the base case after incorporating risk objections: "
                        "short-horizon sentiment and input-cost uncertainty still dominate."
                    ),
                    "evidence_ids": ["news-1"],
                    "cited_memory_ids": ["asset-default-1", critique.get("target_agent", "asset")],
                }
            return LLMResponse(content=json.dumps(payload))

        if "risk_agent" in system_prompt:
            idx = self.role_counts["risk"]
            self.role_counts["risk"] += 1
            if idx == 0:
                payload = {
                    "risk_level": 0.74,
                    "objections": [
                        "Policy details may soften before implementation.",
                        "Existing hedge exposure could cushion margin impact.",
                    ],
                    "suggested_direction": "neutral",
                    "confidence_penalty": 0.18,
                }
            else:
                payload = {
                    "risk_level": 0.36,
                    "objections": ["Policy delay could soften the selloff."],
                    "suggested_direction": "down",
                    "confidence_penalty": 0.08,
                }
            return LLMResponse(content=json.dumps(payload))

        if "critic_agent" in system_prompt:
            idx = self.role_counts["critic"]
            self.role_counts["critic"] += 1
            if idx == 0:
                payload = {
                    "direction_quality": 0.61,
                    "evidence_quality": 0.57,
                    "risk_handling": 0.42,
                    "revision_quality": 0.40,
                    "format_compliance": 1.0,
                    "final_score": 0.58,
                    "verdict": "revise",
                    "blocking_issues_count": 1,
                    "critique_packets": [
                        {
                            "target_agent": "asset",
                            "status": "needs_refine",
                            "severity": "medium",
                            "issues": ["Address why downside still dominates after the stated hedge and policy-delay risks."],
                            "repair_instructions": [
                                "Explicitly integrate the strongest risk objection into the final rationale.",
                                "Calibrate confidence downward if risk remains unresolved.",
                            ],
                            "score": {"risk_handling": 0.42},
                        }
                    ],
                    "notes": ["Asset thesis needs tighter rebuttal of the main objection."],
                }
            else:
                payload = {
                    "direction_quality": 0.82,
                    "evidence_quality": 0.79,
                    "risk_handling": 0.77,
                    "revision_quality": 0.86,
                    "format_compliance": 1.0,
                    "final_score": 0.83,
                    "verdict": "accept",
                    "blocking_issues_count": 0,
                    "critique_packets": [],
                    "notes": ["Converged after targeted asset refinement."],
                }
            return LLMResponse(content=json.dumps(payload))

        if "external reward model" in system_prompt:
            payload = {
                "preference_score": 0.74,
                "outcome_alignment_score": 0.81,
                "human_alignment_score": 0.69,
                "composite_reward": 0.77,
                "reasoning_summary": "Final answer is directionally correct and handles objections better after critique.",
            }
            return LLMResponse(content=json.dumps(payload))

        raise AssertionError(f"Unexpected prompt: {system_prompt}")

    def get_default_model(self) -> str:
        return "scripted-finance-model"


class FakeSubagentManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.role_counts: defaultdict[str, int] = defaultdict(int)

    async def run_and_wait(self, task: str, label: str | None = None, session_key: str | None = None) -> dict:
        role = str(label or "unknown")
        idx = self.role_counts[role]
        self.role_counts[role] += 1
        self.calls.append((role, task, session_key))
        payload: dict
        if role == "news_agent":
            payload = {
                "event_title": "Tariff shock hits electronics supply chain",
                "event_type": "macro_policy",
                "abstract": "Tariff headlines pressure imported-input consumer electronics names.",
                "avg_sentiment": -0.35,
                "importance_score": 0.82,
                "supporting_news_ids": ["news-1"],
                "entities": ["AAPL", "tariffs", "consumer electronics"],
                "evidence_bullets": [
                    "Tariff headlines point to higher input-cost uncertainty.",
                    "Risk-off tape increases sensitivity to margin compression.",
                ],
            }
            if idx > 0:
                payload["evidence_bullets"].append("Refined event framing emphasizes short-horizon sentiment shock.")
        elif role == "asset_agent":
            if idx == 0:
                payload = {
                    "direction": "down",
                    "confidence": 0.62,
                    "rationale": "Tariff shock and risk-off tone likely pressure AAPL over T+3.",
                    "evidence_ids": ["news-1"],
                    "cited_memory_ids": ["asset-default-1"],
                }
            else:
                payload = {
                    "direction": "down",
                    "confidence": 0.56,
                    "rationale": (
                        "Downside remains the base case after incorporating risk objections: "
                        "short-horizon sentiment and input-cost uncertainty still dominate."
                    ),
                    "evidence_ids": ["news-1"],
                    "cited_memory_ids": ["asset-default-1"],
                }
        elif role == "risk_agent":
            if idx == 0:
                payload = {
                    "risk_level": 0.74,
                    "objections": [
                        "Policy details may soften before implementation.",
                        "Existing hedge exposure could cushion margin impact.",
                    ],
                    "suggested_direction": "neutral",
                    "confidence_penalty": 0.18,
                }
            else:
                payload = {
                    "risk_level": 0.36,
                    "objections": ["Policy delay could soften the selloff."],
                    "suggested_direction": "down",
                    "confidence_penalty": 0.08,
                }
        elif role == "critic_agent":
            if idx == 0:
                payload = {
                    "direction_quality": 0.61,
                    "evidence_quality": 0.57,
                    "risk_handling": 0.42,
                    "revision_quality": 0.40,
                    "format_compliance": 1.0,
                    "final_score": 0.58,
                    "verdict": "revise",
                    "blocking_issues_count": 1,
                    "subagent_worklogs": [
                        {
                            "agent_name": "news_agent",
                            "task_id": "new-0",
                            "status": "ok",
                            "input_summary": "Reviewed the tariff headline set and normalized the event.",
                            "output_summary": "Produced a macro_policy event summary with evidence bullets.",
                            "public_contribution": "Shared the event framing and evidence in the roundtable.",
                            "open_issues": [],
                        },
                        {
                            "agent_name": "asset_agent",
                            "task_id": "ass-0",
                            "status": "ok",
                            "input_summary": "Combined event summary and market snapshot for AAPL.",
                            "output_summary": "Produced a bearish T+3 thesis with medium confidence.",
                            "public_contribution": "Shared the first-pass directional view.",
                            "open_issues": ["Needs a stronger rebuttal to hedge and policy-delay risks."],
                        },
                    ],
                    "subagent_critiques": [
                        {
                            "agent_name": "asset_agent",
                            "task_id": "ass-0",
                            "work_quality": 0.61,
                            "evidence_quality": 0.57,
                            "responsiveness_to_critique": 0.40,
                            "summary": "Asset thesis is directionally plausible but under-responds to the top objection.",
                            "strengths": ["Clear directional call."],
                            "weaknesses": ["Risk rebuttal is too thin."],
                            "action_items": ["Address why downside still dominates after hedge and policy-delay risks."],
                            "should_refine": True,
                        }
                    ],
                    "critique_packets": [
                        {
                            "target_agent": "asset",
                            "status": "needs_refine",
                            "severity": "medium",
                            "issues": ["Address why downside still dominates after the stated hedge and policy-delay risks."],
                            "repair_instructions": [
                                "Explicitly integrate the strongest risk objection into the final rationale.",
                                "Calibrate confidence downward if risk remains unresolved.",
                            ],
                            "score": {"risk_handling": 0.42},
                        }
                    ],
                    "notes": ["Asset thesis needs tighter rebuttal of the main objection."],
                }
            else:
                payload = {
                    "direction_quality": 0.82,
                    "evidence_quality": 0.79,
                    "risk_handling": 0.77,
                    "revision_quality": 0.86,
                    "format_compliance": 1.0,
                    "final_score": 0.83,
                    "verdict": "accept",
                    "blocking_issues_count": 0,
                    "subagent_worklogs": [
                        {
                            "agent_name": "asset_agent",
                            "task_id": "ass-1",
                            "status": "ok",
                            "input_summary": "Re-read the critique packet and latest risk view.",
                            "output_summary": "Revised the bearish thesis with lower confidence and explicit rebuttal.",
                            "public_contribution": "Published the updated direction and rationale.",
                            "open_issues": [],
                        }
                    ],
                    "subagent_critiques": [
                        {
                            "agent_name": "asset_agent",
                            "task_id": "ass-1",
                            "work_quality": 0.84,
                            "evidence_quality": 0.79,
                            "responsiveness_to_critique": 0.88,
                            "summary": "Asset agent responded well to critique and closed the main issue.",
                            "strengths": ["Integrated the key objection.", "Adjusted confidence appropriately."],
                            "weaknesses": [],
                            "action_items": [],
                            "should_refine": False,
                        }
                    ],
                    "critique_packets": [],
                    "notes": ["Converged after targeted asset refinement."],
                }
        else:
            raise AssertionError(role)
        return {
            "task_id": f"{role[:3]}-{idx}",
            "label": role,
            "status": "ok",
            "result": json.dumps(payload),
        }


@pytest.mark.asyncio
async def test_finance_service_runs_dynamic_roundtable_and_self_refine(tmp_path):
    provider = ScriptedFinanceProvider()
    subagents = FakeSubagentManager()
    service = FinanceAgenticService(
        provider=provider,
        model="scripted-finance-model",
        workspace=tmp_path,
        max_rounds=3,
        subagents=subagents,
    )

    episode = await service.analyze(_sample_task())

    assert len(episode.rounds) == 2
    assert episode.rounds[0].critic_review.verdict.value == "revise"
    assert episode.rounds[1].critic_review.verdict.value == "accept"
    assert episode.final_asset_output.direction.value == "down"
    assert episode.final_convergence_report.stop_reason == "soft_converged"
    assert any(message.speaker == "risk" for message in episode.rounds[0].roundtable_messages)
    assert any(trace.agent_name == "news_agent" for trace in episode.rounds[0].subagent_traces)
    assert any(trace.agent_name == "critic_agent" for trace in episode.rounds[1].subagent_traces)
    assert any(item.agent_name == "asset_agent" for item in episode.rounds[0].critic_review.subagent_worklogs)
    assert any(item.should_refine for item in episode.rounds[0].critic_review.subagent_critiques)
    assert any(item.agent_name == "risk_agent" for item in episode.rounds[0].critic_review.subagent_worklogs)
    assert all(call[2] is None for call in subagents.calls)
    assert (tmp_path / "finance_agentic" / "episodes" / f"{episode.episode_id}.json").exists()
    log_path = tmp_path / "finance_agentic" / "episodes" / f"{episode.episode_id}.log.md"
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "## Round 1" in log_text
    assert "### Critic Worklogs" in log_text
    assert "### Critic Critiques" in log_text
    assert "### Critique Packets" in log_text


@pytest.mark.asyncio
async def test_finance_reward_pipeline_is_async_and_offpolicy(tmp_path):
    provider = ScriptedFinanceProvider()
    subagents = FakeSubagentManager()
    service = FinanceAgenticService(
        provider=provider,
        model="scripted-finance-model",
        workspace=tmp_path,
        max_rounds=3,
        subagents=subagents,
    )
    episode = await service.analyze(_sample_task())

    reward_store = PersonalizationStore(tmp_path)
    assert not reward_store.reward_requests_path.exists()

    queued = enqueue_offpolicy_reward_requests(tmp_path)

    assert queued == 1
    rows = reward_store.reward_requests_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["episode_id"] == episode.episode_id

    processed = await process_offpolicy_reward_requests(
        workspace=tmp_path,
        provider=provider,
        model="external-reward-model",
        model_version="reward-model-v0",
    )

    score_path = tmp_path / "finance_agentic" / "reward_scores" / f"{episode.episode_id}.json"
    score = json.loads(score_path.read_text(encoding="utf-8"))

    assert processed == 1
    assert score["model_version"] == "reward-model-v0"
    assert score["composite_reward"] == pytest.approx(0.77)


@pytest.mark.asyncio
async def test_finance_command_returns_episode_summary(tmp_path):
    provider = ScriptedFinanceProvider()
    subagents = FakeSubagentManager()
    loop = SimpleNamespace(
        provider=provider,
        model="scripted-finance-model",
        workspace=tmp_path,
        subagents=subagents,
    )
    msg = InboundMessage(
        channel="cli",
        sender_id="u1",
        chat_id="c1",
        content="/finance Tariff shock for AAPL over the next three sessions",
    )
    ctx = CommandContext(
        msg=msg,
        session=None,
        key=msg.session_key,
        raw=msg.content,
        args="Tariff shock for AAPL over the next three sessions",
        loop=loop,
    )

    out = await cmd_finance(ctx)

    assert "Direction: down" in out.content
    assert "Critic verdict: accept" in out.content
    assert out.metadata["render_as"] == "text"
    assert out.metadata["episode_id"]
    assert any(call[2] == msg.session_key for call in subagents.calls)


def test_render_episode_log_contains_subagent_and_critic_sections(tmp_path):
    provider = ScriptedFinanceProvider()
    subagents = FakeSubagentManager()
    service = FinanceAgenticService(
        provider=provider,
        model="scripted-finance-model",
        workspace=tmp_path,
        max_rounds=3,
        subagents=subagents,
    )

    import asyncio

    episode = asyncio.run(service.analyze(_sample_task()))
    log_text = render_episode_log(episode)

    assert "# Finance Episode" in log_text
    assert "### Subagent Traces" in log_text
    assert "### Critic Worklogs" in log_text
    assert "### Critic Critiques" in log_text
