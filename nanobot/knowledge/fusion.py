"""Background fusion and expansion queue for knowledge enrichment."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import KnowledgeExpansionConfig, WebSearchConfig
from nanobot.utils.helpers import ensure_dir, safe_filename


@dataclass
class KnowledgeExpansionJob:
    """One pending background enrichment job."""

    job_id: str
    source_kind: str
    user_key: str
    channel: str
    title: str
    source_url: str | None = None
    source_query: str | None = None
    extracted_links: list[str] = field(default_factory=list)
    suggested_queries: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    excerpt: str | None = None
    derived_from: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeFusionManager:
    """Create persistent expansion jobs and human-readable queue notes."""

    _URL_RE = re.compile(r"https?://[^\s)>\"]+", re.IGNORECASE)

    def __init__(self, root: Path):
        self.root = ensure_dir(root)
        self.queue_dir = ensure_dir(self.root / "inbox")
        self.note_dir = ensure_dir(self.root / "research" / "expansion_queue")

    def enqueue(self, job: KnowledgeExpansionJob) -> KnowledgeExpansionJob:
        queue_path = self.queue_dir / "expansion_jobs.jsonl"
        with open(queue_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(job.to_dict(), ensure_ascii=False) + "\n")

        note_name = safe_filename(f"{job.job_id}-{job.title}")[:120].strip("_") or job.job_id
        note_path = self.note_dir / f"{note_name}.md"
        lines = [
            f"# Expansion Queue: {job.title}",
            "",
            f"- Job ID: {job.job_id}",
            f"- Source Kind: {job.source_kind}",
            f"- User: {job.user_key}",
            f"- Channel: {job.channel}",
        ]
        if job.source_url:
            lines.append(f"- Source URL: {job.source_url}")
        if job.source_query:
            lines.append(f"- Source Query: {job.source_query}")
        if job.tags:
            lines.append(f"- Tags: {', '.join(job.tags)}")
        if job.derived_from:
            lines.append(f"- Derived From: {', '.join(job.derived_from)}")
        lines.extend(["", "## Suggested Queries", ""])
        if job.suggested_queries:
            for query in job.suggested_queries:
                lines.append(f"- {query}")
        else:
            lines.append("- None")
        lines.extend(["", "## Extracted Links", ""])
        if job.extracted_links:
            for link in job.extracted_links:
                lines.append(f"- {link}")
        else:
            lines.append("- None")
        lines.extend(["", "## Excerpt", "", job.excerpt or "(empty)"])
        note_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return job

    def load_pending_jobs(self) -> list[KnowledgeExpansionJob]:
        queue_path = self.queue_dir / "expansion_jobs.jsonl"
        if not queue_path.exists():
            return []
        done = self._done_ids()
        jobs: list[KnowledgeExpansionJob] = []
        for line in queue_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("job_id") in done:
                continue
            jobs.append(KnowledgeExpansionJob(**payload))
        return jobs

    def _done_ids(self) -> set[str]:
        done_path = self.queue_dir / "expansion_done.jsonl"
        if not done_path.exists():
            return set()
        out: set[str] = set()
        for line in done_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            job_id = payload.get("job_id")
            if isinstance(job_id, str) and job_id:
                out.add(job_id)
        return out

    def enqueue_note_path(
        self,
        note_path: Path,
        *,
        user_key: str,
        channel: str,
        source_kind: str = "obsidian",
    ) -> KnowledgeExpansionJob:
        text = note_path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(text)
        title = str(frontmatter.get("title") or note_path.stem)
        tags = self._coerce_str_list(frontmatter.get("tags"))
        links = self._coerce_str_list(frontmatter.get("links"))
        extracted_links = sorted(set([*links, *self._URL_RE.findall(body)]))
        derived_from = self._coerce_str_list(frontmatter.get("derived_from"))
        artifact_id = frontmatter.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            derived_from.append(artifact_id)
        note_rel = note_path.relative_to(self.root)
        if not derived_from:
            derived_from.append(note_rel.as_posix())
        job = KnowledgeExpansionJob(
            job_id=safe_filename(f"promote-{title}")[:80] or "manual-promotion",
            source_kind=source_kind,
            user_key=user_key,
            channel=channel,
            title=title,
            source_url=frontmatter.get("url") if isinstance(frontmatter.get("url"), str) else None,
            source_query=None,
            extracted_links=extracted_links,
            suggested_queries=[title, *tags[:3]],
            tags=tags,
            excerpt=body[:1000] if body else None,
            derived_from=sorted(set(derived_from)),
            metadata={"source_path": note_rel.as_posix()},
        )
        return self.enqueue(job)

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
        if not text.startswith("---\n"):
            return {}, text
        payload = text[4:]
        if "\n---\n" not in payload:
            return {}, text
        raw_meta, body = payload.split("\n---\n", 1)
        try:
            meta = yaml.safe_load(raw_meta) or {}
        except yaml.YAMLError:
            meta = {}
        return meta if isinstance(meta, dict) else {}, body.strip()

    @staticmethod
    def _coerce_str_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []


class KnowledgeExpansionWorker:
    """Process queued jobs into richer fusion notes, optionally with web search."""

    _PAPER_RE = re.compile(r"(arxiv\.org|doi\.org|acm\.org|openreview\.net|paperswithcode\.com)", re.I)
    _CODE_RE = re.compile(r"(github\.com|gitlab\.com)", re.I)
    _BLOG_RE = re.compile(r"(medium\.com|substack\.com|blog\.|docs\.)", re.I)

    def __init__(
        self,
        root: Path,
        *,
        config: KnowledgeExpansionConfig,
        web_search_config: WebSearchConfig | None = None,
        proxy: str | None = None,
    ) -> None:
        self.root = ensure_dir(root)
        self.config = config
        self.manager = KnowledgeFusionManager(root)
        self.output_dir = ensure_dir(self.root / "synthesis" / "fusion")
        self.state_dir = ensure_dir(self.root / "inbox")
        self.web_search = WebSearchTool(web_search_config, proxy=proxy) if config.allow_web_search else None

    def run_pending(self, limit: int | None = None, *, with_search: bool | None = None) -> list[Path]:
        jobs = self.manager.load_pending_jobs()
        if limit is not None:
            jobs = jobs[:limit]
        outputs: list[Path] = []
        for job in jobs:
            outputs.append(self.expand_job(job, with_search=with_search))
        return outputs

    def expand_job(self, job: KnowledgeExpansionJob, *, with_search: bool | None = None) -> Path:
        with_search = self.config.allow_web_search if with_search is None else with_search
        classified = self._classify_links(job.extracted_links[: self.config.max_links_per_job])
        queries = self._trim_queries(job.suggested_queries)
        search_results = self._run_searches(queries) if with_search else {}

        note_name = safe_filename(f"{job.job_id}-{job.title}")[:120].strip("_") or job.job_id
        note_path = self.output_dir / f"{note_name}.md"
        frontmatter = {
            "title": job.title,
            "layer": "synthesis",
            "kind": "fusion",
            "status": "reviewed",
            "claim_type": "synthesis",
            "tags": job.tags,
            "source": job.source_kind,
            "derived_from": job.derived_from,
            "confidence": 0.6 if classified or queries else 0.4,
            "metadata": {
                "job_id": job.job_id,
                "channel": job.channel,
                "user_key": job.user_key,
                "source_url": job.source_url,
                "source_query": job.source_query,
            },
        }
        lines = [
            f"# Knowledge Fusion: {job.title}",
            "",
            f"- Job ID: {job.job_id}",
            f"- Source Kind: {job.source_kind}",
            f"- Channel: {job.channel}",
            f"- User: {job.user_key}",
        ]
        if job.source_url:
            lines.append(f"- Source URL: {job.source_url}")
        if job.source_query:
            lines.append(f"- Source Query: {job.source_query}")
        if job.tags:
            lines.append(f"- Tags: {', '.join(job.tags)}")
        if job.derived_from:
            lines.append(f"- Derived From: {', '.join(job.derived_from)}")

        lines.extend(["", "## Fusion Summary", ""])
        lines.extend(self._summary_lines(job=job, classified=classified, queries=queries))

        lines.extend(["", "## Related Links", ""])
        if classified:
            for kind, urls in classified.items():
                lines.append(f"### {kind.title()}")
                lines.append("")
                for url in urls:
                    lines.append(f"- {url}")
                lines.append("")
        else:
            lines.append("- No outbound links extracted")

        lines.extend(["## Suggested Follow-up Queries", ""])
        if queries:
            for query in queries:
                lines.append(f"- {query}")
        else:
            lines.append("- None")

        if search_results:
            lines.extend(["", "## Web Search Seeds", ""])
            for query, result in search_results.items():
                lines.append(f"### {query}")
                lines.append("")
                lines.append(result.strip() or "(no result)")
                lines.append("")

        lines.extend(["## Source Excerpt", "", job.excerpt or "(empty)", ""])
        note_path.write_text(
            f"---\n{yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()}\n---\n\n"
            + "\n".join(lines).strip()
            + "\n",
            encoding="utf-8",
        )
        self._mark_done(job, note_path)
        return note_path

    def _mark_done(self, job: KnowledgeExpansionJob, note_path: Path) -> None:
        done_path = self.state_dir / "expansion_done.jsonl"
        with open(done_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "job_id": job.job_id,
                "title": job.title,
                "note_path": str(note_path),
            }, ensure_ascii=False) + "\n")

    def _trim_queries(self, queries: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for query in queries:
            normalized = query.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
            if len(out) >= self.config.max_queries_per_job:
                break
        return out

    def _classify_links(self, links: list[str]) -> dict[str, list[str]]:
        out = {"papers": [], "code": [], "blogs": [], "other": []}
        for link in links:
            if self._PAPER_RE.search(link):
                out["papers"].append(link)
            elif self._CODE_RE.search(link):
                out["code"].append(link)
            elif self._BLOG_RE.search(link):
                out["blogs"].append(link)
            else:
                out["other"].append(link)
        return {key: value for key, value in out.items() if value}

    def _summary_lines(
        self,
        *,
        job: KnowledgeExpansionJob,
        classified: dict[str, list[str]],
        queries: list[str],
    ) -> list[str]:
        lines = [
            f"- This expansion job was generated from a `{job.source_kind}` share in `{job.channel}`.",
            f"- Extracted {sum(len(v) for v in classified.values())} outbound links across {len(classified)} categories.",
            f"- Prepared {len(queries)} follow-up research queries for later enrichment.",
        ]
        if "papers" in classified:
            lines.append("- Paper-like links were detected and should be prioritized for factual enrichment.")
        if "code" in classified:
            lines.append("- Code repositories were detected and can be linked to implementation notes.")
        if "blogs" in classified:
            lines.append("- Blog or docs links were detected and can support narrative summaries.")
        return lines

    def _run_searches(self, queries: list[str]) -> dict[str, str]:
        if self.web_search is None:
            return {}
        results: dict[str, str] = {}
        for query in queries:
            try:
                results[query] = asyncio.run(self.web_search.execute(query=query, count=3))
            except Exception as exc:
                results[query] = f"search_failed: {exc}"
        return results
