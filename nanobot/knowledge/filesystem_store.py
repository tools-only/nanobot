"""Filesystem-backed knowledge store for the workspace knowledge vault."""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

import yaml

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
                "kind": artifact.kind,
                "status": artifact.status,
                "claim_type": artifact.claim_type,
                "title": artifact.title,
                "summary": artifact.summary,
                "tags": artifact.tags,
                "links": artifact.links,
                "citations": artifact.citations,
                "derived_from": artifact.derived_from,
                "related_notes": artifact.related_notes,
                "confidence": artifact.confidence,
                "metadata": artifact.metadata,
            }
            body = artifact.content.rstrip() + "\n"
            path.write_text(
                f"---\n{yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()}\n---\n\n{body}",
                encoding="utf-8",
            )

    def get_artifact(self, artifact_id: str) -> KnowledgeArtifact | None:
        for path in self.root.rglob("*.md"):
            artifact = self._parse_artifact(path.read_text(encoding="utf-8"), path=path)
            if artifact is not None and artifact.artifact_id == artifact_id:
                return artifact
        return None

    def query(self, query: KnowledgeQuery) -> list[KnowledgeCandidate]:
        results: list[KnowledgeCandidate] = []
        query_text = query.query.lower().strip()
        for path in self.root.rglob("*.md"):
            artifact = self._parse_artifact(path.read_text(encoding="utf-8"), path=path)
            if artifact is None:
                continue
            if artifact.layer not in query.layers:
                continue
            if query.kinds and artifact.kind not in query.kinds:
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

    def _parse_artifact(self, text: str, *, path: Path | None = None) -> KnowledgeArtifact | None:
        if not text.startswith("---\n"):
            return None
        payload = text[4:]
        if "\n---\n" not in payload:
            return None
        raw_meta, body = payload.split("\n---\n", 1)
        try:
            meta = yaml.safe_load(raw_meta) or {}
        except yaml.YAMLError:
            return None
        if not isinstance(meta, dict):
            return None
        inferred_layer = self._infer_layer(path, meta)
        inferred_kind = self._infer_kind(path, meta, inferred_layer)
        title = meta.get("title") or self._infer_title(path, body)
        if not isinstance(title, str) or not title.strip():
            return None
        artifact_id = meta.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            digest_input = str(path or title)
            digest = sha1(digest_input.encode("utf-8")).hexdigest()[:16]
            artifact_id = f"{meta.get('source_id') or meta.get('source') or 'manual'}:{inferred_layer}:{digest}"
        return KnowledgeArtifact(
            artifact_id=artifact_id,
            source_id=str(meta.get("source_id") or meta.get("source") or "manual:obsidian"),
            layer=inferred_layer,
            kind=inferred_kind,
            status=str(meta.get("status") or "active"),
            claim_type=str(meta.get("claim_type") or ("synthesis" if inferred_layer == "synthesis" else "fact")),
            title=title.strip(),
            content=body.strip(),
            summary=meta.get("summary"),
            tags=self._coerce_str_list(meta.get("tags")),
            links=self._coerce_str_list(meta.get("links")),
            citations=self._coerce_str_list(meta.get("citations")),
            derived_from=self._coerce_str_list(meta.get("derived_from")),
            related_notes=self._coerce_str_list(meta.get("related_notes")),
            confidence=meta.get("confidence"),
            metadata=dict(meta.get("metadata", {}) or {}),
        )

    def _infer_layer(self, path: Path | None, meta: dict) -> str:
        layer = meta.get("layer")
        if isinstance(layer, str) and layer:
            return layer
        if path is None:
            return "canonical"
        rel_parts = path.relative_to(self.root).parts
        if "raw" in rel_parts:
            return "raw"
        if "parsed" in rel_parts:
            return "parsed"
        if "synthesis" in rel_parts:
            return "synthesis"
        if "research" in rel_parts and "fusion" in rel_parts:
            return "synthesis"
        return "canonical"

    def _infer_kind(self, path: Path | None, meta: dict, layer: str) -> str:
        kind = meta.get("kind")
        if isinstance(kind, str) and kind:
            return kind
        if path is not None:
            rel_parts = path.relative_to(self.root).parts
            if "fusion" in rel_parts:
                return "fusion"
            if "topics" in rel_parts:
                return "topic"
            if "concepts" in rel_parts:
                return "concept"
            if "collections" in rel_parts:
                return "archive"
        if layer == "synthesis":
            return "fusion"
        return "archive"

    @staticmethod
    def _infer_title(path: Path | None, body: str) -> str | None:
        for line in body.splitlines():
            normalized = line.strip()
            if normalized.startswith("# "):
                return normalized[2:].strip()
        if path is not None:
            return path.stem.replace("_", " ")
        return None

    @staticmethod
    def _coerce_str_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []
