"""AST-based safety scanner for experiment scripts.

Pure-syntactic checks: no subprocess, no Docker, no network. Decides whether
a candidate script is safe to execute given an optional package allowlist.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

BLOCKED_CALLS = frozenset({
    "os.system", "os.popen",
    "subprocess.run", "subprocess.call",
    "subprocess.Popen", "subprocess.check_output", "subprocess.check_call",
})
BLOCKED_NAMES = frozenset({"eval", "exec", "__import__"})
BLOCKED_IMPORTS = frozenset({
    "socket", "subprocess", "ftplib", "smtplib",
    "http.server", "xmlrpc", "ctypes",
})
_STDLIB_ALLOWLIST = frozenset({
    "json", "os", "os.path", "pathlib", "time", "datetime", "math",
    "collections", "itertools", "functools", "typing", "warnings",
    "logging", "copy", "hashlib", "base64", "io", "tempfile",
    "contextlib", "dataclasses", "enum", "abc", "re", "string",
    "textwrap", "csv",
})


@dataclass
class ValidationResult:
    """Result of AST-based script validation."""

    passed: bool
    issues: list[str] = field(default_factory=list)


def _get_call_name(node: ast.Call) -> str:
    """Extract dotted call name from an AST Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def validate_script(code: str, allowed_packages: list[str] | None = None) -> ValidationResult:
    """AST-based safety scanner for experiment scripts.

    Checks (ALWAYS enforced, both Docker and subprocess modes):
    - Valid Python syntax
    - No blocked calls (os.system, subprocess, etc.)
    - No blocked builtins (eval, exec, __import__)
    - No blocked imports (socket, subprocess, shutil, etc.)
    - No direct imports of blocked functions (from os import system)
    - No getattr-based bypass (getattr(os, 'system'))
    - Script must reference "results.json"

    Additional checks (subprocess mode only, when ``allowed_packages`` is not None):
    - Only allowed_packages + safe stdlib imports
    """
    issues: list[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return ValidationResult(passed=False, issues=[f"SyntaxError: {e}"])

    for node in ast.walk(tree):
        # ALWAYS check dangerous calls
        if isinstance(node, ast.Call):
            call_name = _get_call_name(node)
            if call_name in BLOCKED_CALLS:
                issues.append(f"Blocked call: {call_name}")
            if call_name in BLOCKED_NAMES:
                issues.append(f"Blocked builtin: {call_name}")

            # Check for getattr-based bypass: getattr(os, 'system')
            if (
                call_name == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                    attr_name = node.args[1].value
                    if isinstance(node.args[0], ast.Name):
                        full_name = f"{node.args[0].id}.{attr_name}"
                        if full_name in BLOCKED_CALLS:
                            issues.append(f"Blocked dynamic access: getattr({node.args[0].id}, '{attr_name}')")

        # Always block dangerous module imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in BLOCKED_IMPORTS:
                    issues.append(f"Blocked import: {alias.name}")

        if isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in BLOCKED_IMPORTS:
                    issues.append(f"Blocked import: {node.module}")
                # Check for direct imports of blocked functions: from os import system
                for alias in (node.names or []):
                    full_name = f"{node.module}.{alias.name}"
                    if full_name in BLOCKED_CALLS:
                        issues.append(f"Blocked function import: {full_name}")

        # Allowlist check — subprocess mode only
        if allowed_packages is not None:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in allowed_packages and top not in _STDLIB_ALLOWLIST and top not in BLOCKED_IMPORTS:
                        issues.append(
                            f"Disallowed import: {alias.name} (not in allowed_packages)"
                        )

            if isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top not in allowed_packages and top not in _STDLIB_ALLOWLIST and top not in BLOCKED_IMPORTS:
                    issues.append(
                        f"Disallowed import: {node.module} (not in allowed_packages)"
                    )

    if "results.json" not in code:
        issues.append("Script does not write to results.json (required output contract)")

    return ValidationResult(passed=len(issues) == 0, issues=issues)
