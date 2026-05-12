"""Tests for code execution tool — AST validation, subprocess, sanity check."""
from __future__ import annotations

import asyncio

from academic_pipeline.tools.execution.ast_safety import validate_script
from academic_pipeline.tools.execution.sanity import sanity_check_results
from academic_pipeline.tools.execution.subprocess_runner import execute_script


class TestASTValidation:
    def test_valid_script_passes(self):
        code = (
            "import json\nimport pandas as pd\n"
            "with open('results.json', 'w') as f:\n"
            "    json.dump({'done': True}, f)\n"
        )
        result = validate_script(code, allowed_packages=["pandas"])
        assert result.passed is True
        assert result.issues == []

    def test_syntax_error_fails(self):
        code = "def foo(\n"
        result = validate_script(code, allowed_packages=[])
        assert result.passed is False
        assert any("SyntaxError" in i or "parse" in i.lower() for i in result.issues)

    def test_os_system_blocked(self):
        code = 'import os\nos.system("rm -rf /")\n'
        result = validate_script(code, allowed_packages=["os"])
        assert result.passed is False
        assert any("os.system" in i for i in result.issues)

    def test_subprocess_blocked(self):
        code = "import subprocess\nsubprocess.run(['ls'])\n"
        result = validate_script(code, allowed_packages=["subprocess"])
        assert result.passed is False
        assert any("subprocess" in i for i in result.issues)

    def test_eval_blocked(self):
        code = 'eval("1+1")\n'
        result = validate_script(code, allowed_packages=[])
        assert result.passed is False
        assert any("eval" in i for i in result.issues)

    def test_exec_blocked(self):
        code = 'exec("print(1)")\n'
        result = validate_script(code, allowed_packages=[])
        assert result.passed is False
        assert any("exec" in i for i in result.issues)

    def test_socket_import_blocked(self):
        code = "import socket\n"
        result = validate_script(code, allowed_packages=[])
        assert result.passed is False
        assert any("socket" in i for i in result.issues)

    def test_dunder_import_blocked(self):
        code = '__import__("os")\n'
        result = validate_script(code, allowed_packages=[])
        assert result.passed is False
        assert any("__import__" in i for i in result.issues)

    def test_disallowed_import_blocked(self):
        code = "import boto3\n"
        result = validate_script(code, allowed_packages=["pandas", "sklearn"])
        assert result.passed is False
        assert any("boto3" in i for i in result.issues)

    def test_results_json_required(self):
        code = 'import pandas as pd\nprint("no json output")\n'
        result = validate_script(code, allowed_packages=["pandas"])
        assert result.passed is False
        assert any("results.json" in i for i in result.issues)

    def test_results_json_present_passes(self):
        code = (
            "import json\nimport pandas as pd\n"
            "results = {'metrics': {}}\n"
            "with open('results.json', 'w') as f:\n"
            "    json.dump(results, f)\n"
        )
        result = validate_script(code, allowed_packages=["json", "pandas"])
        assert result.passed is True


class TestScriptExecution:
    def test_successful_execution(self):
        code = (
            "import json\n"
            "results = {'metrics': {'LR': {'accuracy': 0.85}}, 'success': True}\n"
            "with open('results.json', 'w') as f:\n"
            "    json.dump(results, f)\n"
            "print('Done')\n"
        )
        result = asyncio.run(execute_script(code, timeout_seconds=30))
        assert result.success is True
        assert "Done" in result.stdout
        assert result.results_json is not None
        assert result.results_json["metrics"]["LR"]["accuracy"] == 0.85

    def test_timeout_kills_script(self):
        code = "import time\ntime.sleep(60)\n"
        result = asyncio.run(execute_script(code, timeout_seconds=2))
        assert result.success is False
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()

    def test_runtime_error_captured(self):
        code = "raise ValueError('test error')\n"
        result = asyncio.run(execute_script(code, timeout_seconds=10))
        assert result.success is False
        assert "ValueError" in result.stderr or "ValueError" in result.error

    def test_figures_collected(self):
        code = (
            "import json, os\n"
            "os.makedirs('figures', exist_ok=True)\n"
            "with open('figures/test.png', 'wb') as f:\n"
            "    f.write(b'PNG_DATA')\n"
            "with open('results.json', 'w') as f:\n"
            "    json.dump({'metrics': {}}, f)\n"
        )
        result = asyncio.run(execute_script(code, timeout_seconds=30))
        assert result.success is True
        assert len(result.figure_paths) >= 1


class TestSanityCheck:
    def test_normal_results_pass(self):
        results = {
            "metrics": {
                "XGB": {"accuracy": 0.87, "f1": 0.83},
                "LR": {"accuracy": 0.82, "f1": 0.79},
            }
        }
        issues = sanity_check_results(results)
        assert issues == []

    def test_identical_metrics_flagged(self):
        results = {
            "metrics": {
                "XGB": {"accuracy": 0.85},
                "LR": {"accuracy": 0.85},
                "RF": {"accuracy": 0.85},
            }
        }
        issues = sanity_check_results(results)
        assert len(issues) > 0
        assert any("identical" in i.lower() for i in issues)

    def test_suspiciously_high_accuracy_flagged(self):
        results = {"metrics": {"XGB": {"accuracy": 0.999}}}
        issues = sanity_check_results(results)
        assert len(issues) > 0
        assert any("suspicious" in i.lower() or "high" in i.lower() for i in issues)

    def test_nan_metric_flagged(self):
        results = {"metrics": {"XGB": {"accuracy": float("nan")}}}
        issues = sanity_check_results(results)
        assert len(issues) > 0
        assert any("nan" in i.lower() for i in issues)

    def test_negative_metric_flagged(self):
        results = {"metrics": {"XGB": {"accuracy": -0.5}}}
        issues = sanity_check_results(results)
        assert len(issues) > 0
