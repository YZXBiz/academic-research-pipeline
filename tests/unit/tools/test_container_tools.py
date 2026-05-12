"""Tests for container tools (unit tests — mock DockerEnv)."""
from __future__ import annotations

from academic_pipeline.tools.execution.containers import _validate_python, BLOCKED_COMMANDS


def test_validate_python_valid():
    code = "import json\nprint('hello')\n"
    assert _validate_python(code) == []


def test_validate_python_blocks_os_system():
    code = "import os\nos.system('rm -rf /')\n"
    issues = _validate_python(code)
    assert any("os.system" in i for i in issues)


def test_validate_python_blocks_subprocess():
    code = "import subprocess\nsubprocess.run(['ls'])\n"
    issues = _validate_python(code)
    assert len(issues) >= 1


def test_validate_python_syntax_error():
    code = "def f(\n"
    issues = _validate_python(code)
    assert any("SyntaxError" in i for i in issues)


def test_blocked_commands():
    assert "rm -rf /" in BLOCKED_COMMANDS
