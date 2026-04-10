"""Xiaohongshu CLI integration and knowledge collection pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.config.schema import KnowledgeExpansionConfig, XiaohongshuCLIConfig
from nanobot.knowledge.base import CLIKnowledgeAdapter
from nanobot.knowledge.cli_runner import ExternalCLI
from nanobot.knowledge.contracts import (
    KnowledgeIngestRequest,
    KnowledgeIngestResult,
    KnowledgeSourceSpec,
)
from nanobot.knowledge.fusion import KnowledgeExpansionJob, KnowledgeFusionManager
from nanobot.knowledge.pipeline import KnowledgeRuntime
from nanobot.utils.helpers import safe_filename


_XHS_URL_RE = re.compile(r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s]+", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s)>\"]+", re.IGNORECASE)


@dataclass
class XiaohongshuCollectionResult:
    """Structured result for one passive or active XHS collection action."""

    mode: str
    query: str
    artifacts: list[dict[str, Any]]
    warnings: list[str]


class XiaohongshuKnowledgeAdapter(CLIKnowledgeAdapter):
    """Turn Xiaohongshu CLI payloads into layered knowledge artifacts."""

    name = "xiaohongshu-cli"

    def supports(self, source: KnowledgeSourceSpec) -> bool:
        return source.platform == "cli" and source.metadata.get("provider") == "xiaohongshu"

    def ingest(self, request: KnowledgeIngestRequest) -> KnowledgeIngestResult:
        payload = request.payload if isinstance(request.payload, dict) else {"payload": request.payload}
        mode = request.metadata.get("mode", "read")
        note = self._unwrap(payload)
        title = self._get(note, "title", "note_title", "name") or "Xiaohongshu Note"
        desc = self._get(note, "desc", "description", "content", "note_text") or ""
        author = self._get(note, "user_name", "author", "nickname", "user")
        note_url = request.metadata.get("url") or self._get(note, "note_url", "url", "share_url")
        tags = self._extract_tags(note)
        stats = self._extract_stats(note)
        mentions = self._extract_mentions(request.metadata.get("comments", ""))
        domain = self._infer_domain(title=title, desc=desc, tags=tags, note=note)
        subdomain = self._infer_subdomain(tags=tags, title=title)
        content_lines = [
            f"# {title}",
            "",
            f"- Mode: {mode}",
        ]
        content_lines.append(f"- Domain: {domain}")
        if subdomain:
            content_lines.append(f"- Subdomain: {subdomain}")
        if author:
            content_lines.append(f"- Author: {author}")
        if note_url:
            content_lines.append(f"- Source URL: {note_url}")
        if tags:
            content_lines.append(f"- Tags: {', '.join(tags)}")
        if stats:
            stats_text = ", ".join(f"{key}={value}" for key, value in stats.items())
            content_lines.append(f"- Stats: {stats_text}")
        content_lines.extend(["", desc or "(empty)"])
        if request.metadata.get("comments"):
            content_lines.extend(["", "## Comments", "", request.metadata["comments"]])

        outbound_links = self._extract_links(desc)
        summary = desc[:280] if desc else title
        raw_artifact = self.build_artifact(
            source=request.source,
            layer="raw",
            title=title,
            content=self.coerce_text(payload),
            kind="archive",
            domain=domain,
            subdomain=subdomain,
            summary=summary,
            tags=tags,
            citations=[note_url] if note_url else [],
            metadata={
                "mode": mode,
                "vault_dir": f"raw/xiaohongshu/{domain}",
                "vault_name": title,
                **request.metadata,
            },
        )
        parsed_artifact = self.build_artifact(
            source=request.source,
            layer="parsed",
            title=f"{title} Structured Extract",
            content=self._build_structured_extract(
                title=title,
                domain=domain,
                subdomain=subdomain,
                author=author,
                note_url=note_url,
                tags=tags,
                stats=stats,
                mentions=mentions,
                desc=desc,
            ),
            kind="archive",
            domain=domain,
            subdomain=subdomain,
            summary=f"Structured fields extracted from {title}",
            tags=tags,
            links=outbound_links,
            citations=[note_url] if note_url else [],
            derived_from=[raw_artifact.artifact_id],
            metadata={
                "mode": mode,
                "vault_dir": f"parsed/xiaohongshu/{domain}",
                "vault_name": f"{title} Structured Extract",
                **request.metadata,
            },
        )
        canonical_artifact = self.build_artifact(
            source=request.source,
            layer="canonical",
            title=title,
            content="\n".join(content_lines).strip(),
            kind="archive",
            domain=domain,
            subdomain=subdomain,
            summary=summary,
            tags=tags,
            links=outbound_links,
            citations=[note_url] if note_url else [],
            derived_from=[raw_artifact.artifact_id, parsed_artifact.artifact_id],
            metadata={
                "mode": mode,
                "vault_dir": f"canonical/archive/{domain}/xiaohongshu",
                "vault_name": title,
                **request.metadata,
            },
        )
        artifacts = [raw_artifact, parsed_artifact, canonical_artifact]
        return KnowledgeIngestResult(
            source=request.source,
            artifacts=artifacts,
            metadata={"preserve_layers": True, "provider": "xiaohongshu"},
        )

    @staticmethod
    def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload

    @staticmethod
    def _get(payload: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_tags(payload: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        raw = payload.get("tags") or payload.get("tag_list") or payload.get("topics") or []
        for item in raw:
            if isinstance(item, str) and item.strip():
                tags.append(item.strip().lstrip("#"))
            elif isinstance(item, dict):
                name = item.get("name") or item.get("tag") or item.get("title")
                if isinstance(name, str) and name.strip():
                    tags.append(name.strip().lstrip("#"))
        return tags

    @staticmethod
    def _extract_links(text: str) -> list[str]:
        return sorted(set(match.group(0) for match in _URL_RE.finditer(text)))

    @staticmethod
    def _extract_stats(payload: dict[str, Any]) -> dict[str, int]:
        keys = {
            "likes": ("likes", "liked_count", "like_count"),
            "collected": ("collected", "collect_count", "collected_count"),
            "comments": ("comments", "comment_count"),
            "shares": ("shares", "share_count"),
        }
        stats: dict[str, int] = {}
        for output_key, candidates in keys.items():
            for key in candidates:
                value = payload.get(key)
                if isinstance(value, int):
                    stats[output_key] = value
                    break
        return stats

    @staticmethod
    def _extract_mentions(comments_text: str) -> list[str]:
        mentions: list[str] = []
        for line in comments_text.splitlines():
            if "@" not in line:
                continue
            mentions.append(line.strip())
        return mentions[:20]

    @staticmethod
    def _infer_domain(*, title: str, desc: str, tags: list[str], note: dict[str, Any]) -> str:
        text = " ".join([
            title,
            desc,
            " ".join(tags),
            str(note.get("venue", "")),
            str(note.get("arxiv", "")),
        ]).lower()
        if any(keyword in text for keyword in (
            "finance", "financial", "macro", "stock", "equity", "bond", "trading", "market",
            "crypto", "bitcoin", "eth", "基金", "股票", "金融", "宏观", "交易", "投资", "美股", "a股",
        )):
            return "finance"
        if any(keyword in text for keyword in (
            "neurips", "iclr", "icml", "acl", "emnlp", "arxiv", "paper", "survey", "综述", "论文",
        )):
            return "paper"
        if any(keyword in text for keyword in (
            "agent", "agentic", "multi-agent", "智能体", "agent-based",
        )):
            return "agent"
        if any(keyword in text for keyword in (
            "reinforcement learning", "reward model", "policy gradient", "credit assignment", "bandit",
            "强化学习", "奖励模型", "策略梯度", "credit assignment", "rlhf", "grpo",
        )):
            return "rl"
        if any(keyword in text for keyword in (
            "llm", "language model", "transformer", "latent space", "embedding", "token",
            "大模型", "语言模型", "transformer", "潜在空间", "表征学习",
        )):
            return "llm"
        if any(keyword in text for keyword in (
            "infra", "system design", "distributed", "database", "storage", "vector db",
            "基础设施", "系统设计", "数据库", "部署", "架构",
        )):
            return "infra"
        if any(keyword in text for keyword in (
            "product", "growth", "retention", "conversion", "pmf", "用户增长", "转化", "留存", "产品",
        )):
            return "product"
        if any(keyword in text for keyword in (
            "policy", "regulation", "compliance", "governance", "监管", "政策", "合规", "治理",
        )):
            return "policy"
        if any(keyword in text for keyword in (
            "biology", "genome", "protein", "cell", "biology", "生物", "蛋白", "基因", "细胞",
        )):
            return "biology"
        return "other"

    @staticmethod
    def _infer_subdomain(*, tags: list[str], title: str) -> str | None:
        for tag in tags:
            normalized = tag.strip()
            if normalized:
                return normalized
        title_parts = [part.strip() for part in re.split(r"[-_/|:]+", title) if part.strip()]
        if len(title_parts) > 1:
            return title_parts[0][:64]
        return None

    @staticmethod
    def _build_structured_extract(
        *,
        title: str,
        domain: str,
        subdomain: str | None,
        author: str | None,
        note_url: str | None,
        tags: list[str],
        stats: dict[str, int],
        mentions: list[str],
        desc: str,
    ) -> str:
        lines = [
            f"# Structured Extract for {title}",
            "",
            "## Core Fields",
            "",
        ]
        lines.append(f"- Title: {title}")
        lines.append(f"- Domain: {domain}")
        if subdomain:
            lines.append(f"- Subdomain: {subdomain}")
        if author:
            lines.append(f"- Author: {author}")
        if note_url:
            lines.append(f"- Source URL: {note_url}")
        lines.append(f"- Tags: {', '.join(tags) if tags else 'None'}")
        if stats:
            lines.append("- Stats:")
            for key, value in stats.items():
                lines.append(f"  - {key}: {value}")
        else:
            lines.append("- Stats: None")
        lines.extend(["", "## Mention Signals", ""])
        if mentions:
            for mention in mentions:
                lines.append(f"- {mention}")
        else:
            lines.append("- None")
        lines.extend(["", "## Source Excerpt", "", desc or "(empty)"])
        return "\n".join(lines)


class XiaohongshuCLI:
    """Wrapper over the external `xhs` CLI."""

    def __init__(self, config: XiaohongshuCLIConfig):
        self.config = config
        self.cli = ExternalCLI(config.command)

    def available(self) -> bool:
        return self.cli.available()

    def status(self) -> dict[str, Any]:
        status: dict[str, Any] = {"enabled": self.config.enabled, "command": self.config.command, "available": self.available()}
        if self.available():
            result = self.cli.run("status", "--json")
            status["raw"] = result.stdout.strip() if result.ok else result.stderr.strip()
        return status

    def read(self, target: str) -> dict[str, Any]:
        return self.cli.run_json("read", target, "--json")

    def comments(self, target: str) -> dict[str, Any]:
        args = ["comments", target]
        if self.config.collect_comments_all:
            args.append("--all")
        args.append("--json")
        return self.cli.run_json(*args)

    def search(self, query: str, *, sort: str = "latest", page: int = 1) -> dict[str, Any]:
        return self.cli.run_json("search", query, "--sort", sort, "--page", str(page), "--json")


class XiaohongshuKnowledgeCollector:
    """Passive and active knowledge collection driven by xiaohongshu-cli."""

    def __init__(
        self,
        runtime: KnowledgeRuntime,
        root: Path,
        config: XiaohongshuCLIConfig,
        expansion_config: KnowledgeExpansionConfig | None = None,
    ):
        self.runtime = runtime
        self.root = root
        self.config = config
        self.expansion_config = expansion_config or KnowledgeExpansionConfig()
        self.cli = XiaohongshuCLI(config)
        self.fusion = KnowledgeFusionManager(root)

    @staticmethod
    def extract_urls(text: str) -> list[str]:
        return sorted(set(match.group(0) for match in _XHS_URL_RE.finditer(text or "")))

    def collect_url(
        self,
        *,
        url: str,
        user_key: str,
        channel: str,
        queue_expansion: bool | None = None,
    ) -> XiaohongshuCollectionResult:
        warnings: list[str] = []
        artifacts, jobs = self._collect_url(
            url=url,
            user_key=user_key,
            channel=channel,
            warnings=warnings,
            mode="manual_collect",
            queue_expansion=queue_expansion,
        )
        return XiaohongshuCollectionResult(
            mode="active",
            query=url,
            artifacts=[*artifacts, *jobs],
            warnings=warnings,
        )

    def collect_from_message(
        self,
        *,
        text: str,
        user_key: str,
        channel: str,
        queue_expansion: bool | None = None,
    ) -> XiaohongshuCollectionResult | None:
        if not self.config.enabled or not self.config.auto_collect_shared_links:
            return None
        if self.config.passive_allowed_channels and channel not in self.config.passive_allowed_channels:
            return None
        urls = self.extract_urls(text)
        if not urls:
            return None
        artifacts: list[dict[str, Any]] = []
        expansion_jobs: list[dict[str, Any]] = []
        warnings: list[str] = []
        for url in urls:
            collected, jobs = self._collect_url(
                url=url,
                user_key=user_key,
                channel=channel,
                warnings=warnings,
                queue_expansion=queue_expansion,
            )
            artifacts.extend(collected)
            expansion_jobs.extend(jobs)
        return XiaohongshuCollectionResult(
            mode="passive",
            query=text,
            artifacts=[*artifacts, *expansion_jobs],
            warnings=warnings,
        )

    def collect_topic(
        self,
        *,
        topic: str,
        sort: str = "latest",
        limit: int | None = None,
        queue_expansion: bool | None = None,
    ) -> XiaohongshuCollectionResult:
        limit = limit or self.config.active_default_limit
        warnings: list[str] = []
        artifacts: list[dict[str, Any]] = []
        expansion_jobs: list[dict[str, Any]] = []
        if not self.cli.available():
            self._queue_scan(topic=topic, sort=sort)
            warnings.append("xhs_cli_unavailable:queued_scan")
            return XiaohongshuCollectionResult(mode="active", query=topic, artifacts=artifacts, warnings=warnings)

        search_result = self.cli.search(topic, sort=sort, page=1)
        notes = self._extract_notes(search_result)[:limit]
        for note in notes:
            target = note.get("note_id") or note.get("id") or note.get("url") or note.get("share_url")
            if not isinstance(target, str) or not target:
                continue
            collected, jobs = self._collect_url(
                url=target,
                user_key="system:active_scan",
                channel="system",
                warnings=warnings,
                mode="active_topic_scan",
                query=topic,
                queue_expansion=queue_expansion,
            )
            artifacts.extend(collected)
            expansion_jobs.extend(jobs)
        return XiaohongshuCollectionResult(
            mode="active",
            query=topic,
            artifacts=[*artifacts, *expansion_jobs],
            warnings=warnings,
        )

    def _collect_url(
        self,
        *,
        url: str,
        user_key: str,
        channel: str,
        warnings: list[str],
        mode: str = "passive_share",
        query: str | None = None,
        queue_expansion: bool | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self.cli.available():
            self._queue_url(url=url, user_key=user_key, mode=mode, query=query)
            warnings.append(f"xhs_cli_unavailable:queued:{url}")
            return [], []

        note = self.cli.read(url)
        comments_text = ""
        if self.config.collect_comments:
            try:
                comments = self.cli.comments(url)
                comments_text = self._flatten_comments(comments)
            except Exception as exc:
                warnings.append(f"comments_failed:{url}:{exc}")

        source = KnowledgeSourceSpec(
            source_id="xiaohongshu-cli",
            platform="cli",
            namespace="shared",
            metadata={"provider": "xiaohongshu"},
        )
        request = KnowledgeIngestRequest(
            source=source,
            payload=note,
            content_type="application/json",
            external_id=url,
            user_key=user_key,
            metadata={"provider": "xiaohongshu", "mode": mode, "url": url, "query": query, "comments": comments_text},
        )
        result = self.runtime.ingest(request)
        should_queue = self.expansion_config.auto_queue_on_ingest if queue_expansion is None else queue_expansion
        expansion_jobs: list[dict[str, Any]] = []
        if should_queue:
            expansion_job = self.fusion.enqueue(self._build_expansion_job(
                note=note,
                url=url,
                user_key=user_key,
                channel=channel,
                query=query,
                artifact_ids=[artifact.artifact_id for artifact in result.artifacts],
            ))
            expansion_jobs.append(expansion_job.to_dict())
        return [artifact.to_dict() for artifact in result.artifacts], expansion_jobs

    def _queue_url(self, *, url: str, user_key: str, mode: str, query: str | None) -> None:
        path = self.root / "inbox" / "xiaohongshu_url_queue.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "mode": mode,
                "url": url,
                "user_key": user_key,
                "query": query,
            }, ensure_ascii=False) + "\n")

    def _queue_scan(self, *, topic: str, sort: str) -> None:
        path = self.root / "inbox" / "xiaohongshu_topic_queue.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"topic": topic, "sort": sort}, ensure_ascii=False) + "\n")

    @staticmethod
    def _flatten_comments(payload: dict[str, Any]) -> str:
        data = payload.get("data", payload)
        comments = data if isinstance(data, list) else data.get("comments", []) if isinstance(data, dict) else []
        lines: list[str] = []
        for item in comments:
            if not isinstance(item, dict):
                continue
            user = item.get("user_name") or item.get("nickname") or item.get("user") or "unknown"
            content = item.get("content") or item.get("text") or ""
            if content:
                lines.append(f"- {user}: {content}")
        return "\n".join(lines[:100])

    @staticmethod
    def _extract_notes(payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data", payload)
        if isinstance(data, dict):
            for key in ("items", "notes", "list"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _build_expansion_job(
        self,
        *,
        note: dict[str, Any],
        url: str,
        user_key: str,
        channel: str,
        query: str | None,
        artifact_ids: list[str],
    ) -> KnowledgeExpansionJob:
        unwrapped = XiaohongshuKnowledgeAdapter._unwrap(note)
        title = XiaohongshuKnowledgeAdapter._get(unwrapped, "title", "note_title", "name") or "Xiaohongshu Note"
        desc = XiaohongshuKnowledgeAdapter._get(unwrapped, "desc", "description", "content", "note_text") or ""
        tags = XiaohongshuKnowledgeAdapter._extract_tags(unwrapped)
        links = XiaohongshuKnowledgeAdapter._extract_links(desc)
        suggested_queries = [title, *tags[:5], *(f"paper {tag}" for tag in tags[:3])]
        job_id = safe_filename(f"xhs-{title}")[:80] or "xhs-expansion"
        return KnowledgeExpansionJob(
            job_id=job_id,
            source_kind="xiaohongshu",
            user_key=user_key,
            channel=channel,
            title=title,
            source_url=url,
            source_query=query,
            extracted_links=links,
            suggested_queries=suggested_queries,
            tags=tags,
            excerpt=desc[:1000] if desc else None,
            derived_from=artifact_ids,
            metadata={"provider": "xiaohongshu"},
        )


def build_topic_scan_note(root: Path, *, topic: str, result: XiaohongshuCollectionResult) -> Path:
    """Persist a compact active-scan note into the research area."""

    folder = root / "research" / "xiaohongshu"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_filename(topic)}.md"
    lines = [
        f"# Xiaohongshu Topic Scan: {topic}",
        "",
        f"- Mode: {result.mode}",
        f"- Artifacts collected: {len(result.artifacts)}",
        "",
        "## Warnings",
        "",
    ]
    if result.warnings:
        for warning in result.warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
