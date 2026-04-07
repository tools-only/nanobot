"""Lightweight per-user profile storage for personalization."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.personalization.contracts import UserProfileSnapshot
from nanobot.utils.helpers import ensure_dir

_TOPIC_RULES: dict[str, tuple[str, ...]] = {
    "travel": ("travel", "trip", "ticket", "train", "flight", "holiday", "vacation", "itinerary"),
    "schedule": ("schedule", "calendar", "meeting", "remind", "tomorrow", "next week", "deadline"),
    "weather": ("weather", "temperature", "rain", "forecast"),
    "coding": ("code", "bug", "python", "test", "deploy", "api", "repo"),
    "finance": ("stock", "market", "finance", "price", "crypto"),
}


class ProfileStore:
    """Persist sparse user topic counts and compact summaries."""

    def __init__(self, workspace: Path):
        self.dir = ensure_dir(workspace / "personalization")
        self.path = self.dir / "profiles.json"

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict[str, dict]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _build_summary(topic_counts: dict[str, int]) -> str | None:
        ranked = [(topic, count) for topic, count in topic_counts.items() if count > 0]
        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[1], item[0]))
        top = ranked[:2]
        labels = ", ".join(topic for topic, _ in top)
        return f"Observed recurring user interests: {labels}."

    def get_profile(self, user_key: str) -> UserProfileSnapshot:
        data = self._load()
        topic_counts = dict(data.get(user_key, {}).get("topic_counts", {}))
        return UserProfileSnapshot(
            user_key=user_key,
            topic_counts=topic_counts,
            summary=self._build_summary(topic_counts),
        )

    def observe_turn(self, user_key: str, content: str) -> UserProfileSnapshot:
        text = (content or "").lower()
        data = self._load()
        profile = dict(data.get(user_key, {}))
        topic_counts = dict(profile.get("topic_counts", {}))

        for topic, keywords in _TOPIC_RULES.items():
            if any(keyword in text for keyword in keywords):
                topic_counts[topic] = int(topic_counts.get(topic, 0)) + 1

        profile["topic_counts"] = topic_counts
        data[user_key] = profile
        self._save(data)
        return self.get_profile(user_key)
