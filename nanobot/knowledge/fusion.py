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
from nanobot.knowledge.contracts import KnowledgeDomain
from nanobot.utils.helpers import ensure_dir, safe_filename, timestamp


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
    domain: KnowledgeDomain = "other"
    subdomain: str | None = None
    cross_domain: bool = False
    bridges: list[KnowledgeDomain] = field(default_factory=list)
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
        lines.append(f"- Domain: {job.domain}")
        if job.subdomain:
            lines.append(f"- Subdomain: {job.subdomain}")
        if job.cross_domain:
            lines.append("- Cross Domain: true")
        if job.bridges:
            lines.append(f"- Bridges: {', '.join(job.bridges)}")
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
        domain = self._coerce_domain(frontmatter.get("domain"))
        bridges = self._coerce_domain_list(frontmatter.get("bridges"))
        cross_domain = bool(frontmatter.get("cross_domain", False))
        subdomain = frontmatter.get("subdomain") if isinstance(frontmatter.get("subdomain"), str) else None
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
            domain=domain,
            subdomain=subdomain,
            cross_domain=cross_domain,
            bridges=bridges,
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

    @staticmethod
    def _coerce_domain(value: Any) -> KnowledgeDomain:
        if isinstance(value, str) and value in {
            "finance",
            "paper",
            "agent",
            "rl",
            "llm",
            "infra",
            "product",
            "policy",
            "biology",
            "other",
        }:
            return value
        return "other"

    def _coerce_domain_list(self, value: Any) -> list[KnowledgeDomain]:
        out: list[KnowledgeDomain] = []
        for item in self._coerce_str_list(value):
            domain = self._coerce_domain(item)
            if domain not in out:
                out.append(domain)
        return out


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
        self.gist_dir = ensure_dir(self.root / "gist")
        self.state_dir = ensure_dir(self.root / "inbox")
        self.index_path = self.root / "index.md"
        self.log_path = self.root / "log.md"
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
        note_rel = note_path.relative_to(self.root).as_posix()
        source_paths = self._resolve_source_paths(job)
        related_paths = self._discover_related_notes(job, excluded={note_rel, *source_paths})
        frontmatter = {
            "title": job.title,
            "layer": "synthesis",
            "kind": "fusion",
            "status": "reviewed",
            "claim_type": "synthesis",
            "domain": job.domain,
            "subdomain": job.subdomain,
            "cross_domain": job.cross_domain,
            "tags": job.tags,
            "bridges": job.bridges,
            "source": job.source_kind,
            "derived_from": job.derived_from,
            "related_notes": related_paths,
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
        lines.append(f"- Domain: {job.domain}")
        if job.subdomain:
            lines.append(f"- Subdomain: {job.subdomain}")
        if job.cross_domain:
            lines.append("- Cross Domain: true")
        if job.bridges:
            lines.append(f"- Bridges: {', '.join(job.bridges)}")
        if job.derived_from:
            lines.append(f"- Derived From: {', '.join(job.derived_from)}")

        lines.extend(["", "## Fusion Summary", ""])
        lines.extend(self._summary_lines(job=job, classified=classified, queries=queries))

        lines.extend(["", "## Related Existing Notes", ""])
        if related_paths:
            for rel in related_paths:
                lines.append(f"- {rel}")
        else:
            lines.append("- None found")

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
        gist_path = self._write_gist(
            job=job,
            source_paths=source_paths,
            related_paths=related_paths,
            fusion_rel=note_rel,
            classified=classified,
            queries=queries,
            search_results=search_results,
        )
        self._ensure_maintenance_files()
        self._update_index(
            gist_rel=gist_path.relative_to(self.root).as_posix(),
            fusion_rel=note_rel,
        )
        self._append_log(
            job=job,
            fusion_rel=note_rel,
            gist_rel=gist_path.relative_to(self.root).as_posix(),
            source_paths=source_paths,
            related_paths=related_paths,
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
            f"- The source knowledge is classified under the `{job.domain}` domain.",
            f"- Extracted {sum(len(v) for v in classified.values())} outbound links across {len(classified)} categories.",
            f"- Prepared {len(queries)} follow-up research queries for later enrichment.",
        ]
        if job.cross_domain or job.bridges:
            bridges = ", ".join(job.bridges) if job.bridges else "additional domains"
            lines.append(f"- This synthesis can bridge into {bridges}.")
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

    def _resolve_source_paths(self, job: KnowledgeExpansionJob) -> list[str]:
        matches: list[str] = []
        for path in self.root.rglob("*.md"):
            rel = path.relative_to(self.root).as_posix()
            if rel.startswith(".git/"):
                continue
            meta, _ = self._split_frontmatter(path.read_text(encoding="utf-8"))
            artifact_id = meta.get("artifact_id")
            url = meta.get("url")
            source_url = ""
            metadata = meta.get("metadata", {})
            if isinstance(metadata, dict):
                raw_source_url = metadata.get("source_url")
                if isinstance(raw_source_url, str):
                    source_url = raw_source_url
            if isinstance(artifact_id, str) and artifact_id in job.derived_from:
                matches.append(rel)
                continue
            if job.source_url and ((isinstance(url, str) and url == job.source_url) or source_url == job.source_url):
                matches.append(rel)
        return sorted(set(matches))

    def _discover_related_notes(self, job: KnowledgeExpansionJob, *, excluded: set[str]) -> list[str]:
        scored: list[tuple[float, str]] = []
        title_tokens = self._tokenize(job.title)
        query_tokens = self._tokenize(" ".join(job.suggested_queries))
        tag_set = {tag.strip().lower() for tag in job.tags if tag.strip()}
        for base in ("canonical", "synthesis"):
            folder = self.root / base
            if not folder.exists():
                continue
            for path in folder.rglob("*.md"):
                rel = path.relative_to(self.root).as_posix()
                if rel in excluded:
                    continue
                meta, body = self._split_frontmatter(path.read_text(encoding="utf-8"))
                haystack = f"{meta.get('title', '')}\n{' '.join(self._coerce_str_list(meta.get('tags')))}\n{body}".lower()
                score = 0.0
                if isinstance(meta.get("domain"), str) and meta.get("domain") == job.domain:
                    score += 1.5
                if job.subdomain and isinstance(meta.get("subdomain"), str) and meta.get("subdomain") == job.subdomain:
                    score += 1.5
                note_tags = {tag.strip().lower() for tag in self._coerce_str_list(meta.get("tags")) if tag.strip()}
                score += min(2.0, 0.5 * len(tag_set & note_tags))
                score += min(2.0, 0.25 * len([token for token in title_tokens if token in haystack]))
                score += min(1.5, 0.15 * len([token for token in query_tokens if token in haystack]))
                if score <= 0:
                    continue
                scored.append((score, rel))
        scored.sort(key=lambda item: (-item[0], item[1]))
        out: list[str] = []
        seen: set[str] = set()
        for _, rel in scored:
            if rel in seen:
                continue
            seen.add(rel)
            out.append(rel)
            if len(out) >= 5:
                break
        return out

    def _write_gist(
        self,
        *,
        job: KnowledgeExpansionJob,
        source_paths: list[str],
        related_paths: list[str],
        fusion_rel: str,
        classified: dict[str, list[str]],
        queries: list[str],
        search_results: dict[str, str],
    ) -> Path:
        cluster_name = job.subdomain or job.title
        gist_name = safe_filename(f"{job.domain}-{cluster_name}")[:120].strip("_") or safe_filename(job.title) or "knowledge-gist"
        gist_path = self.gist_dir / f"{gist_name}.md"
        covered_notes = sorted(set([*source_paths, *related_paths, fusion_rel]))
        frontmatter = {
            "title": f"{job.title} Gist",
            "layer": "gist",
            "kind": "gist",
            "status": "reviewed",
            "claim_type": "synthesis",
            "domain": job.domain,
            "subdomain": job.subdomain,
            "cluster": cluster_name,
            "tags": job.tags,
            "derived_from": job.derived_from,
            "related_notes": related_paths,
            "covered_notes": covered_notes,
            "updated": timestamp(),
            "metadata": {
                "job_id": job.job_id,
                "source_kind": job.source_kind,
                "source_url": job.source_url,
            },
        }
        lines = [
            f"# {job.title} Gist",
            "",
            "## Scope",
            "",
            f"- Cluster: {cluster_name}",
            f"- Domain: {job.domain}",
        ]
        if job.subdomain:
            lines.append(f"- Subdomain: {job.subdomain}")
        lines.extend([
            "",
            "## Cluster Thesis",
            "",
            f"- This gist compresses the knowledge region around `{job.title}` and its immediately related wiki notes.",
            f"- The current share contributes `{len(job.tags)}` tags, `{sum(len(v) for v in classified.values())}` outbound links, and `{len(queries)}` follow-up research queries.",
        ])
        if related_paths:
            lines.append("- Existing related wiki notes were detected, suggesting this share overlaps with an existing cluster rather than forming an isolated note.")
        else:
            lines.append("- No strong prior wiki cluster was found yet; treat this as a seed cluster until more related notes arrive.")

        lines.extend(["", "## Key Signals", ""])
        if job.tags:
            lines.append(f"- Tags: {', '.join(job.tags)}")
        else:
            lines.append("- Tags: None")
        if classified:
            for kind, urls in classified.items():
                lines.append(f"- {kind.title()}: {len(urls)} link(s)")
        else:
            lines.append("- Outbound links: none")

        lines.extend(["", "## Covered Notes", ""])
        for rel in covered_notes:
            lines.append(f"- {rel}")

        lines.extend(["", "## When To Drill Down", ""])
        lines.append("- Open the fusion note for related links, follow-up queries, and source excerpt.")
        if source_paths:
            lines.append("- Open the source-grounded wiki notes when exact claims, metadata, or citations are needed.")
        if related_paths:
            lines.append("- Open the related wiki notes when comparing with prior concepts or extending the cluster.")

        if queries:
            lines.extend(["", "## Suggested Follow-up Queries", ""])
            for query in queries:
                lines.append(f"- {query}")

        if search_results:
            lines.extend(["", "## Search Seeds", ""])
            for query, result in search_results.items():
                summary = result.strip().splitlines()[0] if result.strip() else "(no result)"
                lines.append(f"- {query}: {summary}")

        gist_path.write_text(
            f"---\n{yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()}\n---\n\n"
            + "\n".join(lines).strip()
            + "\n",
            encoding="utf-8",
        )
        return gist_path

    def _ensure_maintenance_files(self) -> None:
        if not self.index_path.exists():
            self.index_path.write_text(
                "# Knowledge Index\n\n"
                "Canonical navigation file for the vault.\n\n"
                "## Recently Maintained\n\n"
                "- None yet\n",
                encoding="utf-8",
            )
        if not self.log_path.exists():
            self.log_path.write_text(
                "# Knowledge Log\n\n"
                "Append-only record of ingests, promotions, restructures, and lint passes.\n",
                encoding="utf-8",
            )

    def _update_index(self, *, gist_rel: str, fusion_rel: str) -> None:
        text = self.index_path.read_text(encoding="utf-8")
        if "## Recently Maintained" not in text:
            text = text.rstrip() + "\n\n## Recently Maintained\n\n- None yet\n"
        for bullet in (f"- [Latest gist]({gist_rel})", f"- [Latest fusion note]({fusion_rel})"):
            if bullet in text:
                continue
            if "- None yet" in text:
                text = text.replace("- None yet", bullet, 1)
            else:
                text = text.rstrip() + f"\n{bullet}\n"
        self.index_path.write_text(text, encoding="utf-8")

    def _append_log(
        self,
        *,
        job: KnowledgeExpansionJob,
        fusion_rel: str,
        gist_rel: str,
        source_paths: list[str],
        related_paths: list[str],
    ) -> None:
        date_prefix = timestamp().split("T", 1)[0]
        related_text = ", ".join(related_paths) if related_paths else "None"
        source_text = ", ".join(source_paths) if source_paths else "None"
        query_text = ", ".join(self._trim_queries(job.suggested_queries)) if job.suggested_queries else "None"
        review_items = [
            "- Verify that the fusion note reflects the current center of gravity of this cluster.",
            "- Verify that the gist is an appropriate abstraction and not a duplicate of the fusion note.",
            "- Verify whether any related existing notes should be edited manually instead of only being linked.",
        ]
        if not related_paths:
            review_items.append("- Check whether this share should seed a brand-new cluster or be merged into an existing one later.")
        if job.cross_domain or job.bridges:
            review_items.append("- Review the cross-domain bridge decision and confirm the linked domains are justified.")
        if job.source_url:
            review_items.append("- Open the original source and confirm that the key framing was preserved correctly.")
        lines = [
            "",
            f"## [{date_prefix}] maintenance | Processed shared knowledge for {job.title}",
            "",
            "### Trigger",
            "",
            f"- Source kind: `{job.source_kind}`",
            f"- Source URL: {job.source_url or 'None'}",
            f"- User/channel: `{job.user_key}` via `{job.channel}`",
        ]
        lines.extend([
            "",
            "### Decision",
            "",
            f"- Classified domain: `{job.domain}`",
            f"- Subdomain/cluster seed: `{job.subdomain or job.title}`",
            f"- Follow-up queries prepared: {query_text}",
            f"- Related notes discovered before writing: {related_text}",
            "",
            "### Writes",
            "",
            f"- Fusion note: `{fusion_rel}`",
            f"- Gist note: `{gist_rel}`",
            f"- Source-backed note paths resolved: {source_text}",
            "",
            "### Related Notes Considered",
            "",
            f"- {related_text}" if related_paths else "- None",
            "",
            "### Review Checklist",
            "",
            *review_items,
        ])
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

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

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [
            token for token in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text.lower())
            if len(token) >= 2
        ]
