"""Tests for AST safety scan bypass fixes."""
from __future__ import annotations

from academic_pipeline.tools.execution.ast_safety import validate_script


def test_from_os_import_system_blocked():
    code = 'from os import system\nsystem("ls")\nwith open("results.json","w") as f: pass\n'
    result = validate_script(code, allowed_packages=None)
    assert result.passed is False
    assert any("system" in i for i in result.issues)


def test_from_os_import_system_blocked_subprocess_mode():
    code = 'from os import system\nsystem("ls")\nwith open("results.json","w") as f: pass\n'
    result = validate_script(code, allowed_packages=["os"])
    assert result.passed is False
    assert any("system" in i for i in result.issues)


def test_getattr_bypass_blocked():
    code = 'import os\ngetattr(os, "system")("ls")\nwith open("results.json","w") as f: pass\n'
    result = validate_script(code, allowed_packages=None)
    assert result.passed is False
    assert any("getattr" in i for i in result.issues)


def test_blocked_imports_always_checked_in_docker_mode():
    code = 'import subprocess\nwith open("results.json","w") as f: pass\n'
    result = validate_script(code, allowed_packages=None)  # Docker mode
    assert result.passed is False
    assert any("subprocess" in i for i in result.issues)


def test_safe_code_still_passes_docker_mode():
    code = 'import pandas\nimport openai\nwith open("results.json","w") as f: pass\n'
    result = validate_script(code, allowed_packages=None)
    assert result.passed is True
