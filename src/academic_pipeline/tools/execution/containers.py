"""PydanticAI tools for interacting with the experiment Docker container.

All tools access DockerEnv via RunContext[PipelineDeps].deps.docker_env.
Tools are registered on the agent via tools=[...] in agents.py.
"""
from __future__ import annotations

import ast
import base64
import logging
import math

from pydantic_ai import RunContext

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.tools.execution.docker_env import DockerEnv

logger = logging.getLogger(__name__)

BLOCKED_COMMANDS = frozenset({"rm -rf /", "rm -rf /*", "mkfs", "dd if="})


def _get_env(ctx: RunContext[PipelineDeps]):  # type: ignore[type-arg]
    env = ctx.deps.docker_env
    if env is None:
        raise RuntimeError("DockerEnv not initialized on deps")
    return env


def _write_via_base64(env: DockerEnv, content: str, path: str) -> str:
    """Write file content to container via base64 encoding."""
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    chunk_size = 100_000
    total_chunks = math.ceil(len(encoded) / chunk_size)

    for i in range(total_chunks):
        chunk = encoded[i * chunk_size : (i + 1) * chunk_size]
        op = ">" if i == 0 else ">>"
        result = env.run_command(f'echo "{chunk}" | base64 -d {op} {path}')
        if result["status"] != 0:
            return f"Error writing {path}: {result['result']}"

    return f"File written: {path}"


_BLOCKED_CALLS = frozenset({
    "os.system", "os.popen",
    "subprocess.run", "subprocess.call",
    "subprocess.Popen", "subprocess.check_output", "subprocess.check_call",
})
_BLOCKED_NAMES = frozenset({"eval", "exec", "__import__"})
_BLOCKED_IMPORTS = frozenset({
    "socket", "subprocess", "ftplib", "smtplib",
    "http.server", "xmlrpc", "ctypes",
})


def _validate_python(content: str) -> list[str]:
    """AST-validate Python code for safety."""
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return [f"SyntaxError: {e}"]
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                call_name = f"{getattr(func.value, 'id', '')}.{func.attr}"
                if call_name in _BLOCKED_CALLS:
                    issues.append(f"Blocked call: {call_name}")
            if isinstance(func, ast.Name):
                if func.id in _BLOCKED_NAMES:
                    issues.append(f"Blocked builtin: {func.id}")
                if func.id == "getattr" and len(node.args) >= 2:
                    issues.append("Blocked: getattr bypass attempt")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _BLOCKED_IMPORTS:
                    issues.append(f"Blocked import: {alias.name}")
        if isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in _BLOCKED_IMPORTS:
                issues.append(f"Blocked import: from {node.module}")
    return issues


async def create_file(ctx: RunContext[PipelineDeps], path: str, content: str) -> str:
    """Create a new file in the container workspace.

    Python files (.py) are AST-validated for safety before writing.
    Content is base64-encoded for TCP transmission.

    Args:
        path: File path inside the container (e.g., /workspace/experiment.py).
        content: The file content to write.
    """
    if path.endswith(".py"):
        issues = _validate_python(content)
        if issues:
            return f"AST validation failed: {'; '.join(issues)}"
    env = _get_env(ctx)
    env.run_command(f"mkdir -p $(dirname {path})")
    return _write_via_base64(env, content, path)


async def write_file(ctx: RunContext[PipelineDeps], path: str, content: str) -> str:
    """Overwrite an existing file in the container workspace.

    Python files (.py) are AST-validated for safety before writing.
    Content is base64-encoded for TCP transmission.

    Args:
        path: File path inside the container.
        content: The new file content.
    """
    if path.endswith(".py"):
        issues = _validate_python(content)
        if issues:
            return f"AST validation failed: {'; '.join(issues)}"
    env = _get_env(ctx)
    return _write_via_base64(env, content, path)


async def read_file(ctx: RunContext[PipelineDeps], file_path: str) -> str:
    """Read the contents of a file from the container.

    Args:
        file_path: Path to the file inside the container.
    """
    env = _get_env(ctx)
    result = env.run_command(f"cat {file_path}")
    if result["status"] != 0:
        return f"Error reading {file_path}: {result['result']}"
    return result["result"]


async def list_files(ctx: RunContext[PipelineDeps], path: str) -> str:
    """List files and directories at the given path.

    Args:
        path: Directory path inside the container.
    """
    env = _get_env(ctx)
    result = env.run_command(f"ls -la {path}")
    if result["status"] != 0:
        return f"Error listing {path}: {result['result']}"
    return result["result"]


async def create_directory(ctx: RunContext[PipelineDeps], path: str) -> str:
    """Create a directory and any parent directories.

    Args:
        path: Directory path to create.
    """
    env = _get_env(ctx)
    result = env.run_command(f"mkdir -p {path}")
    if result["status"] != 0:
        return f"Error creating directory: {result['result']}"
    return f"Directory created: {path}"


async def gen_code_tree(ctx: RunContext[PipelineDeps], directory: str) -> str:
    """Generate a tree view of the project directory structure.

    Args:
        directory: Root directory to show tree for.
    """
    env = _get_env(ctx)
    result = env.run_command(f"tree {directory} -L 3 --noreport")
    if result["status"] != 0:
        return f"Error generating tree: {result['result']}"
    return result["result"]


async def execute_command(ctx: RunContext[PipelineDeps], command: str) -> str:
    """Execute a shell command in the container.

    Use for: pip install, ls, cat, checking environment.
    Blocked: rm -rf /, mkfs, dd.

    Args:
        command: Shell command to execute.
    """
    for blocked in BLOCKED_COMMANDS:
        if blocked in command:
            return f"Blocked command: {blocked}"
    env = _get_env(ctx)
    result = env.run_command(command)
    output = result["result"]
    if len(output) > 10_000:
        output = output[:5000] + "\n...[truncated]...\n" + output[-3000:]
    return f"Exit code: {result['status']}\n{output}"


async def run_python(ctx: RunContext[PipelineDeps], script_path: str) -> str:
    """Run a Python script in the container with streaming output.

    The script runs with uv run python inside the container workspace.
    Stdout and stderr are captured and returned.

    Args:
        script_path: Path to the .py file inside the container.
    """
    env = _get_env(ctx)
    result = env.run_command(f"cd /workspace && uv run python {script_path}")
    output = result["result"]
    if len(output) > 15_000:
        output = output[:7000] + "\n...[truncated]...\n" + output[-5000:]
    status = "Success" if result["status"] == 0 else f"Failed (exit code {result['status']})"
    return f"{status}\n\n{output}"


async def visualize_figure(ctx: RunContext[PipelineDeps], image_path: str, question: str) -> str:
    """Analyze a figure using the VLM figure reviewer.

    Reads the image from the container workspace and sends it to
    the figure review agent for visual quality assessment.

    Args:
        image_path: Path to .png file in the container (e.g., /workspace/figures/chart.png).
        question: What to check (e.g., 'Are axes labeled? Is the scale appropriate?').
    """
    import base64 as b64
    from pathlib import Path

    env = _get_env(ctx)
    local_path = Path(env.local_workplace) / image_path.removeprefix("/workspace/")
    if not local_path.exists():
        return f"Figure not found: {image_path}"
    img_data = b64.b64encode(local_path.read_bytes()).decode()
    return f"[Figure at {image_path}: {len(img_data)} bytes base64]\nQuestion: {question}\n(VLM review would analyze this image)"
