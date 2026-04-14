from pathlib import Path

from nanobot.config.schema import KnowledgeExpansionConfig, ObsidianCLIConfig, XiaohongshuCLIConfig
from nanobot.knowledge import (
    FilesystemKnowledgeStore,
    KnowledgeExpansionWorker,
    KnowledgeQuery,
    KnowledgeRuntime,
    ObsidianFrontend,
    XiaohongshuKnowledgeAdapter,
    XiaohongshuKnowledgeCollector,
)
from nanobot.knowledge.fusion import KnowledgeExpansionJob, KnowledgeFusionManager


def test_obsidian_frontend_scaffold_creates_vault_layout(tmp_path) -> None:
    frontend = ObsidianFrontend(
        workspace=tmp_path,
        config=ObsidianCLIConfig(enabled=False, auto_scaffold=True),
    )

    frontend.ensure_scaffold()

    assert (frontend.vault_path / "README.md").exists()
    assert (frontend.vault_path / "AGENTS.md").exists()
    assert (frontend.vault_path / "index.md").exists()
    assert (frontend.vault_path / "log.md").exists()
    assert (frontend.vault_path / "canonical" / "archive" / "paper" / "xiaohongshu").exists()
    assert (frontend.vault_path / "canonical" / "concepts" / "paper").exists()
    assert (frontend.vault_path / "gist").exists()
    assert (frontend.vault_path / "synthesis" / "fusion").exists()
    assert (frontend.vault_path / "collections" / "xiaohongshu").exists()


def test_xiaohongshu_collector_queues_when_cli_missing(tmp_path) -> None:
    runtime = KnowledgeRuntime(store=FilesystemKnowledgeStore(tmp_path / "knowledge"))
    runtime.register_adapter(XiaohongshuKnowledgeAdapter())
    collector = XiaohongshuKnowledgeCollector(
        runtime,
        tmp_path / "knowledge",
        XiaohongshuCLIConfig(enabled=True, command="definitely-missing-xhs"),
        KnowledgeExpansionConfig(enabled=True),
    )

    result = collector.collect_from_message(
        text="看看这个 https://www.xiaohongshu.com/explore/abc123",
        user_key="cli:user",
        channel="discord",
    )

    assert result is not None
    assert result.warnings
    assert (tmp_path / "knowledge" / "inbox" / "xiaohongshu_url_queue.jsonl").exists()


def test_xiaohongshu_collector_respects_discord_default_channel(tmp_path) -> None:
    runtime = KnowledgeRuntime(store=FilesystemKnowledgeStore(tmp_path / "knowledge"))
    runtime.register_adapter(XiaohongshuKnowledgeAdapter())
    collector = XiaohongshuKnowledgeCollector(
        runtime,
        tmp_path / "knowledge",
        XiaohongshuCLIConfig(enabled=True, command="definitely-missing-xhs"),
        KnowledgeExpansionConfig(enabled=True),
    )

    result = collector.collect_from_message(
        text="https://www.xiaohongshu.com/explore/abc123",
        user_key="cli:user",
        channel="slack",
    )

    assert result is None


def test_xiaohongshu_url_extraction() -> None:
    urls = XiaohongshuKnowledgeCollector.extract_urls(
        "share https://xhslink.com/abc and https://www.xiaohongshu.com/explore/xyz"
    )

    assert len(urls) == 2


def test_fusion_manager_writes_queue_and_note(tmp_path) -> None:
    fusion = KnowledgeFusionManager(tmp_path / "knowledge")
    job = fusion.enqueue(KnowledgeExpansionJob(
        job_id="xhs-demo",
        source_kind="xiaohongshu",
        user_key="discord:user",
        channel="discord",
        title="Agent Memory Note",
        source_url="https://www.xiaohongshu.com/explore/abc",
        suggested_queries=["agent memory", "paper agent memory"],
        extracted_links=["https://example.com/blog"],
        domain="agent",
        subdomain="memory",
        derived_from=["xiaohongshu-cli:canonical:abc"],
    ))

    assert job.job_id == "xhs-demo"
    assert (tmp_path / "knowledge" / "inbox" / "expansion_jobs.jsonl").exists()
    assert (tmp_path / "knowledge" / "research" / "expansion_queue").exists()


def test_expansion_worker_processes_pending_jobs(tmp_path) -> None:
    root = tmp_path / "knowledge"
    fusion = KnowledgeFusionManager(root)
    canonical_dir = root / "canonical" / "concepts" / "agent"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    (canonical_dir / "memory.md").write_text(
        "---\n"
        "title: Agent Memory\n"
        "layer: canonical\n"
        "kind: concept\n"
        "domain: agent\n"
        "tags: [agent, memory]\n"
        "---\n\n"
        "# Agent Memory\n\n"
        "Agent memory design patterns.\n",
        encoding="utf-8",
    )
    fusion.enqueue(KnowledgeExpansionJob(
        job_id="xhs-demo",
        source_kind="xiaohongshu",
        user_key="discord:user",
        channel="discord",
        title="Agent Memory Note",
        source_url="https://www.xiaohongshu.com/explore/abc",
        suggested_queries=["agent memory", "paper agent memory"],
        extracted_links=["https://github.com/example/repo", "https://arxiv.org/abs/1234.5678"],
        domain="agent",
        subdomain="memory",
        cross_domain=True,
        bridges=["paper"],
        derived_from=["xiaohongshu-cli:canonical:abc"],
    ))

    worker = KnowledgeExpansionWorker(root, config=KnowledgeExpansionConfig(enabled=True, auto_run_on_ingest=False))
    outputs = worker.run_pending(limit=5, with_search=False)

    assert len(outputs) == 1
    assert outputs[0].exists()
    assert "synthesis/fusion" in str(outputs[0])
    assert any((root / "gist").glob("*.md"))
    assert (root / "index.md").exists()
    assert (root / "log.md").exists()
    log_text = (root / "log.md").read_text(encoding="utf-8")
    assert "### Trigger" in log_text
    assert "### Decision" in log_text
    assert "### Writes" in log_text
    assert "### Review Checklist" in log_text
    assert (root / "inbox" / "expansion_done.jsonl").exists()


def test_xiaohongshu_ingest_defaults_to_low_level_archive(tmp_path) -> None:
    root = tmp_path / "knowledge"
    runtime = KnowledgeRuntime(store=FilesystemKnowledgeStore(root))
    runtime.register_adapter(XiaohongshuKnowledgeAdapter())
    collector = XiaohongshuKnowledgeCollector(
        runtime,
        root,
        XiaohongshuCLIConfig(enabled=True, command="xhs"),
        KnowledgeExpansionConfig(enabled=True, auto_queue_on_ingest=False),
    )

    collector.cli.available = lambda: True
    collector.cli.read = lambda target: {
        "data": {
            "title": "Latent Space Survey",
            "desc": "See https://arxiv.org/abs/1234.5678 for details",
            "tags": ["latent-space", "survey"],
            "nickname": "Author A",
            "like_count": 12,
        }
    }
    collector.cli.comments = lambda target: {"data": [{"nickname": "tester", "content": "@NanoFlash nice"}]}

    result = collector.collect_from_message(
        text="https://www.xiaohongshu.com/explore/abc123",
        user_key="cli:user",
        channel="discord",
    )

    assert result is not None
    assert len(result.artifacts) == 3
    assert {artifact.domain for artifact in result.artifacts} == {"paper"}
    assert result.artifacts[0].subdomain == "latent-space"
    assert not (root / "inbox" / "expansion_jobs.jsonl").exists()
    assert any((root / "raw" / "xiaohongshu" / "paper").glob("*.md"))
    assert any((root / "parsed" / "xiaohongshu" / "paper").glob("*.md"))
    assert any((root / "canonical" / "archive" / "paper" / "xiaohongshu").glob("*.md"))
    assert not any((root / "synthesis").rglob("*.md"))


def test_xiaohongshu_auto_run_implies_queue(tmp_path) -> None:
    root = tmp_path / "knowledge"
    runtime = KnowledgeRuntime(store=FilesystemKnowledgeStore(root))
    runtime.register_adapter(XiaohongshuKnowledgeAdapter())
    collector = XiaohongshuKnowledgeCollector(
        runtime,
        root,
        XiaohongshuCLIConfig(enabled=True, command="xhs"),
        KnowledgeExpansionConfig(enabled=True, auto_queue_on_ingest=False, auto_run_on_ingest=True),
    )

    collector.cli.available = lambda: True
    collector.cli.read = lambda target: {
        "data": {
            "title": "Agent Memory Note",
            "desc": "See https://arxiv.org/abs/1234.5678 for details",
            "tags": ["agent", "memory"],
            "nickname": "Author A",
        }
    }
    collector.cli.comments = lambda target: {"data": []}

    result = collector.collect_from_message(
        text="https://www.xiaohongshu.com/explore/abc123",
        user_key="cli:user",
        channel="discord",
    )

    assert result is not None
    assert any(item.get("job_id") for item in result.artifacts if isinstance(item, dict))
    assert (root / "inbox" / "expansion_jobs.jsonl").exists()


def test_filesystem_store_reads_yaml_archive_notes_across_custom_dirs(tmp_path) -> None:
    root = tmp_path / "knowledge"
    note_dir = root / "collections" / "xiaohongshu"
    note_dir.mkdir(parents=True, exist_ok=True)
    note = note_dir / "demo.md"
    note.write_text(
        "---\n"
        "title: Demo Note\n"
        "source: xiaohongshu\n"
        "tags: [latent-space, survey]\n"
        "---\n\n"
        "# Demo Note\n\n"
        "Latent space summary.\n",
        encoding="utf-8",
    )

    store = FilesystemKnowledgeStore(root)
    matches = store.query(KnowledgeQuery(query="latent", layers=["canonical"], kinds=["archive"]))

    assert len(matches) == 1
    assert matches[0].artifact.title == "Demo Note"
    assert matches[0].artifact.layer == "canonical"
    assert matches[0].artifact.kind == "archive"
    assert matches[0].artifact.domain == "other"


def test_fusion_manager_can_enqueue_existing_note_for_promotion(tmp_path) -> None:
    root = tmp_path / "knowledge"
    note_dir = root / "canonical" / "archive" / "paper" / "xiaohongshu"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "demo.md"
    note_path.write_text(
        "---\n"
        "title: Demo Archive\n"
        "artifact_id: demo:canonical:123\n"
        "domain: paper\n"
        "subdomain: survey\n"
        "tags: [agent-memory, survey]\n"
        "links:\n"
        "  - https://arxiv.org/abs/1234.5678\n"
        "---\n\n"
        "# Demo Archive\n\n"
        "Archive body.\n",
        encoding="utf-8",
    )

    manager = KnowledgeFusionManager(root)
    job = manager.enqueue_note_path(note_path, user_key="cli:manual", channel="cli")

    assert job.title == "Demo Archive"
    assert job.domain == "paper"
    assert job.subdomain == "survey"
    assert "demo:canonical:123" in job.derived_from
    assert (root / "inbox" / "expansion_jobs.jsonl").exists()


def test_filesystem_store_can_filter_by_domain(tmp_path) -> None:
    root = tmp_path / "knowledge"
    paper_dir = root / "canonical" / "archive" / "paper" / "xiaohongshu"
    finance_dir = root / "canonical" / "archive" / "finance" / "xiaohongshu"
    paper_dir.mkdir(parents=True, exist_ok=True)
    finance_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "paper.md").write_text(
        "---\n"
        "title: Paper Note\n"
        "domain: paper\n"
        "tags: [survey]\n"
        "---\n\n"
        "# Paper Note\n\n"
        "latent space survey\n",
        encoding="utf-8",
    )
    (finance_dir / "finance.md").write_text(
        "---\n"
        "title: Finance Note\n"
        "domain: finance\n"
        "tags: [macro]\n"
        "---\n\n"
        "# Finance Note\n\n"
        "latent liquidity conditions\n",
        encoding="utf-8",
    )

    store = FilesystemKnowledgeStore(root)
    matches = store.query(KnowledgeQuery(query="latent", layers=["canonical"], kinds=["archive"], domains=["paper"]))

    assert len(matches) == 1
    assert matches[0].artifact.title == "Paper Note"
    assert matches[0].artifact.domain == "paper"
