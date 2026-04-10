"""Helpers for shelling out to external knowledge CLIs."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CommandResult:
    """Structured command execution result."""

    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class ExternalCLI:
    """Small wrapper around a named external CLI binary."""

    def __init__(self, command: str, *, cwd: Path | None = None):
        self.command = command
        self.cwd = cwd

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def run(self, *args: str, cwd: Path | None = None) -> CommandResult:
        argv = [self.command, *args]
        proc = subprocess.run(
            argv,
            cwd=str(cwd or self.cwd) if (cwd or self.cwd) else None,
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandResult(argv=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

    def run_json(self, *args: str, cwd: Path | None = None) -> dict[str, Any]:
        result = self.run(*args, cwd=cwd)
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(result.argv)}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid json from {' '.join(result.argv)}") from exc
