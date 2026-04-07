"""Turn telemetry and reward-oriented factor collection."""

from __future__ import annotations

from collections import Counter
from typing import Any

from nanobot.personalization.contracts import ExposurePlan

_TOOL_CATEGORY_MAP = {
    "web_search": "search",
    "web_fetch": "search",
    "cron": "schedule",
    "message": "messaging",
    "exec": "execution",
    "read_file": "filesystem",
    "write_file": "filesystem",
    "edit_file": "filesystem",
    "list_dir": "filesystem",
}


def _trace_preview(content: Any, limit: int = 240) -> str | None:
    if isinstance(content, str):
        return content[:limit]
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            joined = "\n".join(parts)
            return joined[:limit]
    return None


class TurnTelemetryCollector:
    """Collect reward-relevant trajectory factors from a completed turn."""

    def build_trace(self, new_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        trace: list[dict[str, Any]] = []
        for message in new_messages:
            role = message.get("role")
            entry: dict[str, Any] = {
                "role": role,
                "name": message.get("name"),
                "tool_call_id": message.get("tool_call_id"),
            }
            preview = _trace_preview(message.get("content"))
            if preview:
                entry["content_preview"] = preview
            if role == "assistant" and message.get("tool_calls"):
                entry["tool_calls"] = [
                    tc.get("function", {}).get("name") or tc.get("name")
                    for tc in message.get("tool_calls", [])
                    if isinstance(tc, dict)
                ]
            trace.append(entry)
        return trace

    def collect(
        self,
        *,
        plan: ExposurePlan,
        final_content: str | None,
        new_messages: list[dict[str, Any]],
        tools_used: list[str],
        usage: dict[str, int],
        delivered_via_message_tool: bool,
        feedback_signals: dict[str, Any],
    ) -> dict[str, Any]:
        tool_counts = Counter(tools_used)
        tool_categories = Counter(_TOOL_CATEGORY_MAP.get(tool, "other") for tool in tools_used)
        mcp_tools = [tool for tool in tools_used if tool.startswith("mcp_")]
        mcp_servers_used = sorted(
            {server for server in (self._extract_mcp_server(tool) for tool in mcp_tools) if server}
        )
        selected_by_surface = Counter(item.surface for item in plan.selected_items)
        candidate_by_surface = Counter(item.surface for item in plan.candidates)
        response_text = final_content or ""
        lowered = plan.state.current_message.lower()
        time_sensitive_query = any(keyword in lowered for keyword in ("latest", "today", "now", "news", "price", "weather", "今天", "现在"))

        return {
            "candidate_count": len(plan.candidates),
            "selected_count": len(plan.selected_items),
            "candidate_by_surface": dict(candidate_by_surface),
            "selected_by_surface": dict(selected_by_surface),
            "dynamic_block_count": len(plan.dynamic_blocks),
            "tool_names_used": list(tools_used),
            "tool_call_count": len(tools_used),
            "tool_counts": dict(tool_counts),
            "tool_categories": dict(tool_categories),
            "mcp_tools_used": mcp_tools,
            "mcp_servers_used": mcp_servers_used,
            "available_mcp_servers": list(plan.state.mcp_servers),
            "active_skills": list(plan.state.active_skills),
            "used_search": bool(tool_categories.get("search")),
            "used_schedule": bool(tool_categories.get("schedule")),
            "used_execution": bool(tool_categories.get("execution")),
            "used_filesystem": bool(tool_categories.get("filesystem")),
            "used_message_tool": delivered_via_message_tool,
            "response_chars": len(response_text),
            "response_empty": not bool(response_text.strip()),
            "response_question_count": response_text.count("?") + response_text.count("？"),
            "response_has_action_language": any(
                token in response_text.lower()
                for token in ("can", "could", "next", "schedule", "recommend", "suggest")
            ),
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "message_count": len(new_messages),
            "time_sensitive_query": time_sensitive_query,
            "search_matched_time_sensitivity": time_sensitive_query and bool(tool_categories.get("search")),
            "feedback_positive": bool(feedback_signals.get("explicit_positive")),
            "feedback_negative": bool(feedback_signals.get("explicit_negative")),
            "feedback_correction": bool(feedback_signals.get("correction_signal")),
            "feedback_preference": bool(feedback_signals.get("preference_signal")),
        }

    @staticmethod
    def _extract_mcp_server(tool_name: str) -> str | None:
        if not tool_name.startswith("mcp_"):
            return None
        rest = tool_name[4:]
        if "_" not in rest:
            return None
        return rest.split("_", 1)[0]
