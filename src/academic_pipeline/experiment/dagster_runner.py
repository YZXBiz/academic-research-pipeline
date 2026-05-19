"""Subprocess invocation of `dagster job execute` inside a workspace dir."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DagsterRunResult:
    succeeded: bool
    returncode: int
    results_json_path: Path
    stdout: str
    stderr: str


def run_dagster_job(
    workspace: Path,
    timeout_s: int = 1800,
) -> DagsterRunResult:
    """Run `uv run dagster job execute -m pipeline.definitions` in workspace.

    Workspace must contain pyproject.toml + src/pipeline/ + config.yaml."""
    if not (workspace / "config.yaml").exists():
        raise FileNotFoundError(f"config.yaml missing in {workspace}")
    if not (workspace / "src" / "pipeline" / "definitions.py").exists():
        raise FileNotFoundError(f"src/pipeline/definitions.py missing in {workspace}")

    # ensure venv is synced (idempotent)
    subprocess.run(
        ["uv", "sync"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )
    # PYTHONPATH=src needed because Python 3.13 silently skips hatchling's
    # underscore-prefixed `_editable_impl_*.pth` files, so the workspace's
    # `pipeline` package isn't importable from a uv-managed venv. Without
    # this, dagster job execute fails at module-load with
    # `DagsterImportError: No module named 'pipeline'`.
    env = {**os.environ, "PYTHONPATH": str(workspace / "src")}
    proc = subprocess.run(
        ["uv", "run", "dagster", "job", "execute", "-m", "pipeline.definitions"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    results_path = workspace / "results.json"
    return DagsterRunResult(
        succeeded=proc.returncode == 0 and results_path.exists(),
        returncode=proc.returncode,
        results_json_path=results_path,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def load_results_json(path: Path) -> dict:
    return json.loads(path.read_text())
