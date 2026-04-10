"""Filesystem-backed knowledge store for the workspace knowledge vault."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.knowledge.base import KnowledgeStore
from nanobot.knowledge.contracts import KnowledgeArtifact, KnowledgeCandidate, KnowledgeQuery
from nanobot.utils.helpers import ensure_dir, safe_filename


class FilesystemKnowledgeStore(KnowledgeStore):
    """Persist knowledge artifacts as markdown files inside the workspace vault."""

    def __init__(self, root: Path):
        self.root = ensure_dir(root)

    def _layer_dir(self, layer: str) -> Path:
        return ensure_dir(self.root / layer)

    def _artifact_path(self, artifact: KnowledgeArtifact) -> Path:
        custom_dir = artifact.metadata.get("vault_dir")
        custom_name = artifact.metadata.get("vault_name")
        name = safe_filename(f"{artifact.artifact_id}-{artifact.title}")[:120].strip("_") or artifact.artifact_id
        if isinstance(custom_name, str) and custom_name.strip():
            name = safe_filename(custom_name)[:120].strip("_") or name
        if isinstance(custom_dir, str) and custom_dir.strip():
            return ensure_dir(self.root / custom_dir) / f"{name}.md"
        return self._layer_dir(artifact.layer) / f"{name}.md"

    def write_artifacts(self, artifacts: list[KnowledgeArtifact]) -> None:
        for artifact in artifacts:
            path = self._artifact_path(artifact)
            frontmatter = {
                "artifact_id": artifact.artifact_id,
                "source_id": artifact.source_id,
                "layer": artifact.layer,
                "title": artifact.title,
                "summary": artifact.summary,
                "tags": artifact.tags,
                "links": artifact.links,
                "citations": artifact.citations,
                "metadata": artifact.metadata,
            }
            body = artifact.content.rstrip() + "\n"
            path.write_text(
                f"---\n{json.dumps(frontmatter, ensure_ascii=False, indent=2)}\n---\n\n{body}",
                encoding="utf-8",
            )

    def get_artifact(self, artifact_id: str) -> KnowledgeArtifact | None:
        for path in self.root.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if f'"artifact_id": "{artifact_id}"' not in text:
                continue
            return self._parse_artifact(text)
        return None

    def query(self, query: KnowledgeQuery) -> list[KnowledgeCandidate]:
        results: list[KnowledgeCandidate] = []
        query_text = query.query.lower().strip()
        for layer in query.layers:
            layer_dir = self.root / layer
            if not layer_dir.exists():
                continue
            for path in layer_dir.rglob("*.md"):
                text = path.read_text(encoding="utf-8")
                artifact = self._parse_artifact(text)
                if artifact is None:
                    continue
                haystack = f"{artifact.title}\n{artifact.summary or ''}\n{artifact.content}".lower()
                score = 0.0
                if query_text and query_text in haystack:
                    score += 1.0
                if query.tags:
                    score += len(set(query.tags) & set(artifact.tags)) * 0.25
                if score <= 0:
                    continue
                results.append(KnowledgeCandidate(artifact=artifact, score=score, reasons=["filesystem_match"]))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[: query.max_results]

    @staticmethod
    def _parse_artifact(text: str) -> KnowledgeArtifact | None:
        if not text.startswith("---\n"):
            return None
        _, raw_meta, body = text.split("---\n", 2)
        try:
            meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            return None
        return KnowledgeArtifact(
            artifact_id=meta["artifact_id"],
            source_id=meta["source_id"],
            layer=meta["layer"],
            title=meta["title"],
            content=body.strip(),
            summary=meta.get("summary"),
            tags=list(meta.get("tags", [])),
            links=list(meta.get("links", [])),
            citations=list(meta.get("citations", [])),
            metadata=dict(meta.get("metadata", {})),
        )
