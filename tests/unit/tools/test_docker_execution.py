"""Tests for Docker execution helpers and routing."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from academic_pipeline.tools.execution.ast_safety import validate_script
from academic_pipeline.tools.execution.subprocess_runner import (
    _docker_available,
    _ensure_docker_image,
)


class TestDockerHelpers:
    @patch("academic_pipeline.tools.execution.subprocess_runner._subprocess.run")
    def test_docker_available_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert _docker_available() is True

    @patch("academic_pipeline.tools.execution.subprocess_runner._subprocess.run")
    def test_docker_available_false_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        assert _docker_available() is False

    @patch("academic_pipeline.tools.execution.subprocess_runner._subprocess.run")
    def test_docker_available_false_not_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert _docker_available() is False

    @patch("academic_pipeline.tools.execution.subprocess_runner._subprocess.run")
    def test_ensure_image_exists(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert _ensure_docker_image("test:latest") is True

    @patch("academic_pipeline.tools.execution.subprocess_runner._subprocess.run")
    def test_ensure_image_missing(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert _ensure_docker_image("test:latest") is False


class TestValidateScriptDockerMode:
    def test_docker_mode_skips_import_checks(self):
        code = 'import boto3\nimport openai\nwith open("results.json", "w") as f:\n    pass\n'
        result = validate_script(code, allowed_packages=None)
        assert result.passed is True

    def test_docker_mode_still_blocks_dangerous_calls(self):
        code = 'import os\nos.system("rm -rf /")\nwith open("results.json", "w") as f:\n    pass\n'
        result = validate_script(code, allowed_packages=None)
        assert result.passed is False
        assert any("os.system" in i for i in result.issues)

    def test_docker_mode_still_blocks_eval(self):
        code = 'eval("1+1")\nwith open("results.json", "w") as f:\n    pass\n'
        result = validate_script(code, allowed_packages=None)
        assert result.passed is False
        assert any("eval" in i for i in result.issues)

    def test_subprocess_mode_still_checks_imports(self):
        code = 'import boto3\nwith open("results.json", "w") as f:\n    pass\n'
        result = validate_script(code, allowed_packages=["pandas", "sklearn"])
        assert result.passed is False
        assert any("boto3" in i for i in result.issues)
