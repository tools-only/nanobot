"""Personalization middleware gateway."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.skills import SkillsLoader
from nanobot.config.loader import load_config
from nanobot.config.paths import get_knowledge_path
from nanobot.knowledge import (
    FilesystemKnowledgeStore,
    KnowledgeExpansionWorker,
    KnowledgeRuntime,
    ObsidianFrontend,
    XiaohongshuKnowledgeAdapter,
    XiaohongshuKnowledgeCollector,
)
from nanobot.memory_layers import LayeredMemoryManager, MemoryObservation
from nanobot.personalization.assembler import ExposureAssembler
from nanobot.personalization.candidate_generators import CandidateGenerators
from nanobot.personalization.contracts import ExposurePlan
from nanobot.personalization.feedback import FeedbackExtractor
from nanobot.personalization.online_eval import LightweightOnlineRewardEvaluator
from nanobot.personalization.profile_store import ProfileStore
from nanobot.personalization.providers import ContextVariableRegistry
from nanobot.personalization.reward_assigner import RewardAssigner
from nanobot.personalization.router import ExposureRouter
from nanobot.personalization.score_tables import ScoreTables
from nanobot.personalization.shortlist import CandidateShortlister
from nanobot.personalization.state_builder import StateBuilder
from nanobot.personalization.store import PersonalizationStore
from nanobot.personalization.telemetry import TurnTelemetryCollector


class PersonalizationGateway:
    """End-to-end personalization middleware with typed recall and logging."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.config = load_config()
        self.knowledge_root = get_knowledge_path(workspace, self.config.knowledge.root)
        self.skills_loader = SkillsLoader(workspace)
        self.knowledge = KnowledgeRuntime(workspace, store=FilesystemKnowledgeStore(self.knowledge_root))
        self.knowledge.register_adapter(XiaohongshuKnowledgeAdapter())
        self.obsidian = ObsidianFrontend(self.workspace, self.config.knowledge.obsidian, knowledge_root=self.knowledge_root)
        if self.config.knowledge.obsidian.auto_scaffold:
            self.obsidian.ensure_scaffold()
        self.xiaohongshu = XiaohongshuKnowledgeCollector(
            self.knowledge,
            self.knowledge_root,
            self.config.knowledge.xiaohongshu,
        )
        self.expansion = KnowledgeExpansionWorker(
            self.knowledge_root,
            config=self.config.knowledge.expansion,
            web_search_config=self.config.tools.web.search,
            proxy=self.config.tools.web.proxy,
        )
        self.memory_layers = LayeredMemoryManager()
        self.providers = ContextVariableRegistry()
        self.profile_store = ProfileStore(workspace)
        self.score_tables = ScoreTables(workspace)
        self.state_builder = StateBuilder()
        self.generators = CandidateGenerators(self.score_tables, providers=self.providers)
        self.shortlister = CandidateShortlister()
        self.online_eval = LightweightOnlineRewardEvaluator()
        self.router = ExposureRouter()
        self.assembler = ExposureAssembler()
        self.store = PersonalizationStore(workspace)
        self.reward_assigner = RewardAssigner()
        self.feedback = FeedbackExtractor()
        self.telemetry = TurnTelemetryCollector()

    def before_turn(self, msg, session, *, mcp_servers: dict[str, Any] | None = None) -> ExposurePlan:
        profile = self.profile_store.get_profile(f"{msg.channel}:{msg.sender_id or msg.chat_id}")
        state = self.state_builder.build_with_context(
            msg,
            session,
            profile=profile,
            active_skills=self._active_skill_summaries(),
            mcp_servers=self._mcp_context(mcp_servers or {}),
        )
        candidates = self.generators.generate(state)
        shortlisted = self.shortlister.shortlist(state, candidates)
        shortlisted, online_eval = self.online_eval.evaluate(state=state, shortlisted=shortlisted)
        plan = self.router.plan(
            state,
            candidates=candidates,
            shortlisted=shortlisted,
            online_eval=online_eval,
        )
        plan.dynamic_blocks = self.assembler.build_blocks(plan)
        return plan

    def after_turn(
        self,
        *,
        msg,
        session,
        plan: ExposurePlan | None,
        final_content: str | None,
        new_messages: list[dict[str, Any]],
        tools_used: list[str],
        usage: dict[str, int],
        delivered_via_message_tool: bool,
    ) -> None:
        if plan is None:
            return

        profile = self.profile_store.observe_turn(plan.state.user_key, msg.content)
        feedback_signals = self.feedback.extract(msg.content)
        trace = self.telemetry.build_trace(new_messages)
        proxy_metrics = self.telemetry.collect(
            plan=plan,
            final_content=final_content,
            new_messages=new_messages,
            tools_used=tools_used,
            usage=usage,
            delivered_via_message_tool=delivered_via_message_tool,
            feedback_signals=feedback_signals,
        )
        memory_units = self.memory_layers.observe(MemoryObservation(
            user_key=plan.state.user_key,
            session_key=plan.state.session_key,
            content=self._memory_observation_content(msg.content, final_content),
            role="turn",
            outcome="responded" if final_content else "empty_response",
            metadata={"channel": msg.channel, "chat_id": msg.chat_id},
        ))
        memory_promotions = self.memory_layers.evaluate_promotions(memory_units)
        knowledge_activity = self.xiaohongshu.collect_from_message(
            text=msg.content,
            user_key=plan.state.user_key,
            channel=msg.channel,
        )
        expansion_outputs: list[str] = []
        if knowledge_activity is not None and self.config.knowledge.expansion.enabled and self.config.knowledge.expansion.auto_run_on_ingest:
            expansion_outputs = [str(path) for path in self.expansion.run_pending(limit=5, with_search=False)]
        self.store.append_turn({
            "event": "turn_completed",
            "user_key": plan.state.user_key,
            "session_key": plan.state.session_key,
            "profile": profile.to_dict(),
            "plan": plan.to_dict(),
            "feedback_signals": feedback_signals,
            "proxy_metrics": proxy_metrics,
            "trace": trace,
            "layered_memory": {
                "units": [unit.to_dict() for unit in memory_units],
                "promotion_decisions": [decision.to_dict() for decision in memory_promotions],
            },
            "knowledge_activity": {
                "obsidian": self.obsidian.status(include_version=False),
                "xiaohongshu": None if knowledge_activity is None else {
                    "mode": knowledge_activity.mode,
                    "query": knowledge_activity.query,
                    "artifacts": knowledge_activity.artifacts,
                    "warnings": knowledge_activity.warnings,
                },
                "expansion_outputs": expansion_outputs,
            },
            "final_content": final_content,
            "message_count": len(new_messages),
        })
        request = self.reward_assigner.build_request(
            plan=plan,
            final_content=final_content,
            feedback_signals=feedback_signals,
            proxy_metrics=proxy_metrics,
            trace=trace,
        )
        self.store.append_reward_request(request.to_dict())

    def _active_skill_summaries(self) -> list[dict[str, str]]:
        skills: list[dict[str, str]] = []
        for name in self.skills_loader.get_always_skills():
            meta = self.skills_loader.get_skill_metadata(name) or {}
            skills.append({
                "name": name,
                "description": meta.get("description", name),
                "source": "always",
            })
        return skills

    @staticmethod
    def _mcp_context(mcp_servers: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, cfg in mcp_servers.items():
            out.append({
                "server": name,
                "transport": getattr(cfg, "type", None) or ("stdio" if getattr(cfg, "command", None) else "http"),
                "enabled_tools": list(getattr(cfg, "enabled_tools", []) or []),
            })
        return out

    @staticmethod
    def _memory_observation_content(user_content: str, final_content: str | None) -> str:
        if final_content:
            return f"User: {user_content}\nAssistant: {final_content}"
        return f"User: {user_content}"
