from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse


def test_build_messages_includes_adaptive_blocks(tmp_path) -> None:
    builder = ContextBuilder(tmp_path)
    messages = builder.build_messages(
        history=[],
        current_message="hello",
        dynamic_blocks=["## User Profile Signal\nObserved recurring user interests: travel."],
        channel="cli",
        chat_id="direct",
    )

    assert messages[0]["role"] == "system"
    assert "# Adaptive Context" in messages[0]["content"]
    assert "Observed recurring user interests: travel." in messages[0]["content"]


@pytest.mark.asyncio
async def test_personalization_gateway_logs_turns_and_adapts_next_turn(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok"))
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="ok"))

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    await loop.process_direct(
        "I want holiday train tickets",
        session_key="cli:test",
        channel="cli",
        chat_id="direct",
    )
    await loop.process_direct(
        "Plan another holiday train trip",
        session_key="cli:test",
        channel="cli",
        chat_id="direct",
    )

    second_call = provider.chat_with_retry.await_args_list[-1]
    messages = second_call.kwargs["messages"]
    assert "# Adaptive Context" in messages[0]["content"]
    assert "travel" in messages[0]["content"]
    assert (tmp_path / "personalization" / "turns.jsonl").exists()
    assert (tmp_path / "personalization" / "reward_requests.jsonl").exists()
    turns_text = (tmp_path / "personalization" / "turns.jsonl").read_text(encoding="utf-8")
    requests_text = (tmp_path / "personalization" / "reward_requests.jsonl").read_text(encoding="utf-8")
    assert '"feedback_signals"' in turns_text
    assert '"proxy_metrics"' in turns_text
    assert '"trace"' in turns_text
    assert '"active_skills"' in turns_text
    assert '"available_mcp_servers"' in turns_text
    assert '"candidate_items"' in requests_text
    assert '"shortlisted_items"' in requests_text
    assert '"online_eval"' in requests_text
