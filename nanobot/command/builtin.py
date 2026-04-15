"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import os
import sys

from nanobot import __version__
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.finance_agentic import (
    FinanceAgenticService,
    enqueue_offpolicy_reward_requests,
    format_episode_summary,
    process_offpolicy_reward_requests,
)
from nanobot.finance_agentic.service import parse_finance_task_argument
from nanobot.utils.helpers import build_status_content


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    tasks = loop._active_tasks.pop(msg.session_key, [])
    cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    sub_cancelled = await loop.subagents.cancel_by_session(msg.session_key)
    total = cancelled + sub_cancelled
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="Restarting...")


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    try:
        ctx_est, _ = loop.memory_consolidator.estimate_session_prompt_tokens(session)
    except Exception:
        pass
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__, model=loop.model,
            start_time=loop._start_time, last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
        ),
        metadata={"render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a fresh session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated:]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.memory_consolidator.archive_messages(snapshot))
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content="New session started.",
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    lines = [
        "🐈 nanobot commands:",
        "/new — Start a new conversation",
        "/stop — Stop the current task",
        "/restart — Restart the bot",
        "/status — Show bot status",
        "/help — Show available commands",
        "/finance — Run the finance roundtable workflow",
        "/finance-enqueue-reward — Queue off-policy reward scoring",
        "/finance-score-reward — Process queued reward scoring",
    ]
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata={"render_as": "text"},
    )


async def cmd_finance_help(ctx: CommandContext) -> OutboundMessage:
    """Return finance workflow command help."""
    content = "\n".join(
        [
            "Finance agentic commands:",
            "/finance <task-json | task-file | thesis>",
            "/finance-enqueue-reward",
            "/finance-score-reward",
        ]
    )
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


async def cmd_finance(ctx: CommandContext) -> OutboundMessage:
    """Run the finance roundtable workflow on a single task."""
    task = parse_finance_task_argument(ctx.args, ctx.loop.workspace)
    service = FinanceAgenticService(
        provider=ctx.loop.provider,
        model=ctx.loop.model,
        workspace=ctx.loop.workspace,
    )
    episode = await service.analyze(task)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=format_episode_summary(episode),
        metadata={"render_as": "text", "episode_id": episode.episode_id},
    )


async def cmd_finance_enqueue_reward(ctx: CommandContext) -> OutboundMessage:
    """Queue finance episodes for async off-policy reward scoring."""
    queued = enqueue_offpolicy_reward_requests(ctx.loop.workspace)
    content = f"Queued {queued} finance reward request(s)."
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


async def cmd_finance_score_reward(ctx: CommandContext) -> OutboundMessage:
    """Process queued off-policy finance reward requests."""
    processed = await process_offpolicy_reward_requests(
        workspace=ctx.loop.workspace,
        provider=ctx.loop.provider,
        model=ctx.loop.model,
    )
    content = f"Processed {processed} finance reward score(s)."
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/help", cmd_help)
    router.exact("/finance", cmd_finance_help)
    router.exact("/finance-enqueue-reward", cmd_finance_enqueue_reward)
    router.exact("/finance-score-reward", cmd_finance_score_reward)
    router.prefix("/finance ", cmd_finance)
