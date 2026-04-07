"""Trajectory storage for personalization middleware."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import ensure_dir, timestamp


class PersonalizationStore:
    """Append-only JSONL stores for turns and reward-assignment requests."""

    def __init__(self, workspace: Path):
        self.dir = ensure_dir(workspace / "personalization")
        self.turns_path = self.dir / "turns.jsonl"
        self.reward_requests_path = self.dir / "reward_requests.jsonl"

    @staticmethod
    def _append(path: Path, payload: dict[str, Any]) -> None:
        row = dict(payload)
        row.setdefault("timestamp", timestamp())
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def append_turn(self, payload: dict[str, Any]) -> None:
        self._append(self.turns_path, payload)

    def append_reward_request(self, payload: dict[str, Any]) -> None:
        self._append(self.reward_requests_path, payload)
