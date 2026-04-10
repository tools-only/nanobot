from pathlib import Path

from nanobot.config.schema import KnowledgeExpansionConfig, ObsidianCLIConfig, XiaohongshuCLIConfig
from nanobot.knowledge import (
    FilesystemKnowledgeStore,
    KnowledgeExpansionWorker,
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
    assert (frontend.vault_path / "canonical").exists()
    assert (frontend.vault_path / "collections" / "xiaohongshu").exists()


def test_xiaohongshu_collector_queues_when_cli_missing(tmp_path) -> None:
    runtime = KnowledgeRuntime(store=FilesystemKnowledgeStore(tmp_path / "knowledge"))
    runtime.register_adapter(XiaohongshuKnowledgeAdapter())
    collector = XiaohongshuKnowledgeCollector(
        runtime,
        tmp_path / "knowledge",
        XiaohongshuCLIConfig(enabled=True, command="definitely-missing-xhs"),
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
    ))

    worker = KnowledgeExpansionWorker(root, config=KnowledgeExpansionConfig(enabled=True, auto_run_on_ingest=True))
    outputs = worker.run_pending(limit=5, with_search=False)

    assert len(outputs) == 1
    assert outputs[0].exists()
    assert (root / "inbox" / "expansion_done.jsonl").exists()
