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
    assert (frontend.vault_path / "canonical" / "archive" / "xiaohongshu").exists()
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
        derived_from=["xiaohongshu-cli:canonical:abc"],
    ))

    assert job.job_id == "xhs-demo"
    assert (tmp_path / "knowledge" / "inbox" / "expansion_jobs.jsonl").exists()
    assert (tmp_path / "knowledge" / "research" / "expansion_queue").exists()


def test_expansion_worker_processes_pending_jobs(tmp_path) -> None:
    root = tmp_path / "knowledge"
    fusion = KnowledgeFusionManager(root)
    fusion.enqueue(KnowledgeExpansionJob(
        job_id="xhs-demo",
        source_kind="xiaohongshu",
        user_key="discord:user",
        channel="discord",
        title="Agent Memory Note",
        source_url="https://www.xiaohongshu.com/explore/abc",
        suggested_queries=["agent memory", "paper agent memory"],
        extracted_links=["https://github.com/example/repo", "https://arxiv.org/abs/1234.5678"],
        derived_from=["xiaohongshu-cli:canonical:abc"],
    ))

    worker = KnowledgeExpansionWorker(root, config=KnowledgeExpansionConfig(enabled=True, auto_run_on_ingest=False))
    outputs = worker.run_pending(limit=5, with_search=False)

    assert len(outputs) == 1
    assert outputs[0].exists()
    assert "synthesis/fusion" in str(outputs[0])
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
    assert not (root / "inbox" / "expansion_jobs.jsonl").exists()
    assert any((root / "raw" / "xiaohongshu").glob("*.md"))
    assert any((root / "parsed" / "xiaohongshu").glob("*.md"))
    assert any((root / "canonical" / "archive" / "xiaohongshu").glob("*.md"))
    assert not any((root / "synthesis").rglob("*.md"))


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


def test_fusion_manager_can_enqueue_existing_note_for_promotion(tmp_path) -> None:
    root = tmp_path / "knowledge"
    note_dir = root / "canonical" / "archive" / "xiaohongshu"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "demo.md"
    note_path.write_text(
        "---\n"
        "title: Demo Archive\n"
        "artifact_id: demo:canonical:123\n"
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
    assert "demo:canonical:123" in job.derived_from
    assert (root / "inbox" / "expansion_jobs.jsonl").exists()
