"""Subprocess + Docker runner for experiment scripts.

Runs validated Python scripts either inside the experiment Docker image or
as a local subprocess fallback, then collects ``results.json`` and figures.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess as _subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of script execution via subprocess."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    results_json: dict | None = None
    figure_paths: list[str] = field(default_factory=list)
    figure_data: dict[str, str] = field(default_factory=dict)


def _docker_available() -> bool:
    """Check if Docker daemon is running."""
    try:
        result = _subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, _subprocess.TimeoutExpired):
        return False


def _ensure_docker_image(image_name: str) -> bool:
    """Check if a Docker image exists locally."""
    try:
        result = _subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(
                "Docker image '%s' not found. Run 'make docker-build-sandbox' to build it.",
                image_name,
            )
        return result.returncode == 0
    except (FileNotFoundError, _subprocess.TimeoutExpired):
        return False


def _collect_artifacts(tmpdir: Path) -> tuple[dict | None, list[str], dict[str, str]]:
    """Read results.json and collect figure files from a temp directory."""
    results_json = None
    results_path = tmpdir / "results.json"
    if results_path.exists():
        try:
            results_json = json.loads(results_path.read_text())
        except json.JSONDecodeError:
            results_json = None

    figure_paths: list[str] = []
    figure_data: dict[str, str] = {}
    figures_dir = tmpdir / "figures"
    if figures_dir.exists():
        for fig_file in sorted(figures_dir.iterdir()):
            if fig_file.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".pdf"):
                figure_paths.append(fig_file.name)
                figure_data[fig_file.name] = base64.b64encode(fig_file.read_bytes()).decode("ascii")

    return results_json, figure_paths, figure_data


async def _execute_in_subprocess(code: str, timeout_seconds: int = 600) -> ExecutionResult:
    """Run a Python script in a temp directory via asyncio subprocess.

    - Creates a temp directory, writes experiment.py
    - Sets MPLBACKEND=Agg
    - Enforces timeout
    - Reads results.json and figures/ after completion
    - Cleans up temp dir
    """
    tmpdir = tempfile.mkdtemp(prefix="experiment_")
    try:
        script_path = Path(tmpdir) / "experiment.py"
        script_path.write_text(code)

        env = {**os.environ, "MPLBACKEND": "Agg"}

        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                str(script_path),
                cwd=tmpdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except Exception as e:
            return ExecutionResult(success=False, error=f"Failed to start process: {e}")

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            return ExecutionResult(
                success=False,
                error=f"Script timed out after {timeout_seconds} seconds",
            )

        stdout = (
            stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        )
        stderr = (
            stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        )

        if proc.returncode != 0:
            return ExecutionResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                error=f"Script exited with code {proc.returncode}",
            )

        results_json, figure_paths, figure_data = _collect_artifacts(Path(tmpdir))
        if results_json is None and (Path(tmpdir) / "results.json").exists():
            return ExecutionResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                error="results.json is not valid JSON",
            )

        return ExecutionResult(
            success=True,
            stdout=stdout,
            stderr=stderr,
            results_json=results_json,
            figure_paths=figure_paths,
            figure_data=figure_data,
        )
    finally:
        # Clean up temp dir
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


async def _execute_in_docker(code: str, timeout_seconds: int) -> ExecutionResult:
    """Run experiment script inside a Docker container."""
    from academic_pipeline.config import get_config

    config = get_config()
    container_name = f"exp-{uuid.uuid4().hex[:12]}"
    tmpdir_base = Path(".pipeline_runs/tmp")
    tmpdir_base.mkdir(parents=True, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="experiment_", dir=str(tmpdir_base))

    try:
        script_path = Path(tmpdir) / "experiment.py"
        script_path.write_text(code)
        (Path(tmpdir) / "figures").mkdir(exist_ok=True)

        # Only pass API keys if explicitly enabled
        env_args: list[str] = []
        if config.experiment_docker_pass_api_keys:
            for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "EXA_API_KEY", "HF_TOKEN"):
                val = os.environ.get(key)
                if val:
                    env_args.extend(["-e", f"{key}={val}"])

        abs_tmpdir = str(Path(tmpdir).resolve())
        cmd = [
            "docker",
            "run",
            "--name",
            container_name,
            "--rm",
            "-v",
            f"{abs_tmpdir}:/workspace/run",
            "-w",
            "/workspace/run",
            *env_args,
            "-e",
            "MPLBACKEND=Agg",
            "--network=bridge",
            f"--memory={config.experiment_docker_memory}",
            f"--cpus={config.experiment_docker_cpus}",
            config.experiment_docker_image,
            "uv",
            "run",
            "python",
            "experiment.py",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            kill_proc = await asyncio.create_subprocess_exec(
                "docker",
                "kill",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await kill_proc.wait()
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            return ExecutionResult(
                success=False,
                error=f"Docker container timed out after {timeout_seconds} seconds",
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        if proc.returncode != 0:
            return ExecutionResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                error=f"Container exited with code {proc.returncode}",
            )

        results_json, figure_paths, figure_data = _collect_artifacts(Path(tmpdir))
        if results_json is None and (Path(tmpdir) / "results.json").exists():
            return ExecutionResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                error="results.json is not valid JSON",
            )

        return ExecutionResult(
            success=True,
            stdout=stdout,
            stderr=stderr,
            results_json=results_json,
            figure_paths=figure_paths,
            figure_data=figure_data,
        )
    finally:
        import shutil as _shutil

        _shutil.rmtree(tmpdir, ignore_errors=True)


async def execute_script(code: str, timeout_seconds: int = 1800) -> ExecutionResult:
    """Run experiment script -- Docker if available, subprocess fallback."""
    from academic_pipeline.config import get_config

    config = get_config()
    if (
        config.experiment_use_docker
        and _docker_available()
        and _ensure_docker_image(config.experiment_docker_image)
    ):
        return await _execute_in_docker(code, timeout_seconds)
    return await _execute_in_subprocess(code, timeout_seconds)
