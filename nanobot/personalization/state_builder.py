"""State builder for personalization middleware."""

from __future__ import annotations

from typing import Any

from nanobot.personalization.contracts import RuntimeState, UserProfileSnapshot


class StateBuilder:
    """Normalize runtime state before candidate generation."""

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(parts)
        return ""

    def build(self, msg, session, profile: UserProfileSnapshot | None = None) -> RuntimeState:
        return self.build_with_context(msg, session, profile=profile)

    def build_with_context(
        self,
        msg,
        session,
        *,
        profile: UserProfileSnapshot | None = None,
        active_skills: list[dict[str, str]] | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> RuntimeState:
        recent_user_messages: list[str] = []
        for entry in reversed(session.messages):
            if entry.get("role") != "user":
                continue
            text = self._extract_text(entry.get("content"))
            if text:
                recent_user_messages.append(text)
            if len(recent_user_messages) >= 3:
                break

        recent_user_messages.reverse()
        user_key = f"{msg.channel}:{msg.sender_id or msg.chat_id}"
        return RuntimeState(
            user_key=user_key,
            session_key=msg.session_key,
            channel=msg.channel,
            chat_id=msg.chat_id,
            sender_id=msg.sender_id,
            current_message=msg.content,
            recent_user_messages=recent_user_messages,
            active_skills=list(active_skills or []),
            mcp_servers=list(mcp_servers or []),
            profile=profile,
        )
