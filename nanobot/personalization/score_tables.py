"""Sparse score tables used for typed candidate recall."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.personalization.contracts import SurfaceType
from nanobot.utils.helpers import ensure_dir

_SURFACE_PRIORS: dict[SurfaceType, float] = {
    "context_evidence": 0.20,
    "capability_exposure": 0.10,
    "acquisition_policy": 0.05,
    "interaction_hint": 0.10,
}


class ScoreTables:
    """Store global/cohort/user priors for exposure recall."""

    def __init__(self, workspace: Path):
        self.dir = ensure_dir(workspace / "personalization")
        self.path = self.dir / "scores.json"

    def _load(self) -> dict:
        if not self.path.exists():
            return {"global": {}, "cohort": {}, "user": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"global": {}, "cohort": {}, "user": {}}

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _item_id(surface: SurfaceType, item_key: str) -> str:
        return f"{surface}:{item_key}"

    def get_recall_prior(
        self,
        *,
        user_key: str,
        item_key: str,
        surface: SurfaceType,
        cohort_key: str = "default",
    ) -> float:
        data = self._load()
        item_id = self._item_id(surface, item_key)
        global_score = float(data["global"].get(item_id, _SURFACE_PRIORS.get(surface, 0.0)))
        cohort_score = float(data["cohort"].get(cohort_key, {}).get(item_id, 0.0))
        user_score = float(data["user"].get(user_key, {}).get(item_id, 0.0))
        return global_score + cohort_score + user_score

    def apply_assignment(
        self,
        *,
        user_key: str,
        item_scores: dict[str, float],
        surface_by_item: dict[str, SurfaceType],
        cohort_key: str = "default",
    ) -> None:
        """Update sparse priors from asynchronous reward-assignment results."""
        if not item_scores:
            return
        data = self._load()
        data.setdefault("global", {})
        data.setdefault("cohort", {})
        data["cohort"].setdefault(cohort_key, {})
        data.setdefault("user", {})
        data["user"].setdefault(user_key, {})

        for item_key, delta in item_scores.items():
            surface = surface_by_item.get(item_key)
            if surface is None:
                continue
            item_id = self._item_id(surface, item_key)
            data["global"][item_id] = float(data["global"].get(item_id, _SURFACE_PRIORS.get(surface, 0.0))) + delta * 0.1
            data["cohort"][cohort_key][item_id] = float(data["cohort"][cohort_key].get(item_id, 0.0)) + delta * 0.2
            data["user"][user_key][item_id] = float(data["user"][user_key].get(item_id, 0.0)) + delta * 0.5

        self._save(data)
