"""Obsidian CLI integration used as the knowledge-base frontend."""

from __future__ import annotations

from pathlib import Path

from nanobot.config.paths import get_knowledge_path
from nanobot.config.schema import ObsidianCLIConfig
from nanobot.knowledge.cli_runner import ExternalCLI
from nanobot.utils.helpers import ensure_dir


_KNOWN_DOMAINS = (
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
)


class ObsidianFrontend:
    """Bridge to Obsidian CLI for browsing and editing the knowledge vault."""

    def __init__(self, workspace: Path, config: ObsidianCLIConfig, *, knowledge_root: Path | None = None):
        self.workspace = workspace
        self.config = config
        self.vault_path = get_knowledge_path(workspace, config.vault_path) if knowledge_root is None else knowledge_root
        self.cli = ExternalCLI(config.command, cwd=self.vault_path)

    def ensure_scaffold(self) -> None:
        ensure_dir(self.vault_path)
        folders = {
            "raw",
            "raw/xiaohongshu",
            "parsed",
            "parsed/xiaohongshu",
            "canonical",
            "canonical/archive",
            "canonical/concepts",
            "synthesis",
            "synthesis/topics",
            "synthesis/fusion",
            "inbox",
            "collections/xiaohongshu",
            "research/xiaohongshu",
            "research/expansion_queue",
        }
        for domain in _KNOWN_DOMAINS:
            folders.add(f"raw/xiaohongshu/{domain}")
            folders.add(f"parsed/xiaohongshu/{domain}")
            folders.add(f"canonical/archive/{domain}/xiaohongshu")
            folders.add(f"canonical/concepts/{domain}")
        for folder in sorted(folders):
            ensure_dir(self.vault_path / folder)

        index = self.vault_path / "README.md"
        if not index.exists():
            index.write_text(
                "# Knowledge Vault\n\n"
                "- `raw/<source>/<domain>/`: source captures organized by source and domain\n"
                "- `parsed/<source>/<domain>/`: structured extracts without interpretation\n"
                "- `canonical/archive/<domain>/<source>/`: normalized archive notes\n"
                "- `canonical/concepts/<domain>/`: stable single-concept notes\n"
                "- `synthesis/topics/`: cross-source topic notes\n"
                "- `synthesis/fusion/`: high-level linked synthesis notes, often cross-domain\n"
                "- `research/expansion_queue/`: explicit promotion queue\n",
                encoding="utf-8",
            )

    def status(self, *, include_version: bool = True) -> dict[str, object]:
        info: dict[str, object] = {
            "enabled": self.config.enabled,
            "command": self.config.command,
            "available": self.cli.available(),
            "vault_path": str(self.vault_path),
        }
        if include_version and self.cli.available():
            version = self.cli.run("version")
            info["version"] = version.stdout.strip() if version.ok else None
        return info

    def search(self, query: str, limit: int = 20) -> dict:
        return self.cli.run_json("search", f"query={query}", f"limit={limit}", "format=json")

    def read(self, path: str) -> str:
        result = self.cli.run("read", f"path={path}")
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"failed to read {path}")
        return result.stdout

    def create_or_overwrite(self, path: str, content: str, *, open_file: bool = False) -> None:
        args = ["create", f"path={path}", f"content={content}", "overwrite"]
        if open_file:
            args.append("open")
        result = self.cli.run(*args)
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"failed to create {path}")

    def append(self, path: str, content: str) -> None:
        result = self.cli.run("append", f"path={path}", f"content={content}")
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"failed to append {path}")

    def open(self, path: str) -> None:
        result = self.cli.run("open", f"path={path}")
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"failed to open {path}")
