"""PRD §6.12.T7 — declared-but-unused dependency hygiene checks.

These tests pin the dependency surface area decided in §6.12.T7:

- `fastapi` and `uvicorn` are removed (zero src/ imports; no dashboard v2 HTTP
  endpoint shipped — §6.8.T5 deferred per blockers.md).
- `pydantic-ai[mcp]` and `pydantic-ai[dbos]` extras are removed
  (DBOS confirmed disabled; no MCP usage per CLAUDE.md). Code paths that
  reference DBOS remain ImportError-gated, so removing the extra does not
  break the pipeline.
- `defusedxml` stays as an explicit pin: a transitive consumer
  (`py-serializable` via cyclonedx via pip-audit) keeps it in the resolved
  set, but explicit pin avoids a future implicit-removal regression.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def project_table() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]


def _direct_dep_names(project: dict) -> set[str]:
    """Return the set of bare distribution names in project.dependencies."""
    out: set[str] = set()
    for entry in project["dependencies"]:
        # Strip extras and version specifier; keep only the name.
        # e.g. "pydantic-ai[anthropic,logfire]>=0.2.0" -> "pydantic-ai"
        name = entry.split("[", 1)[0]
        for sep in (">=", "<=", "==", "!=", "~=", ">", "<"):
            if sep in name:
                name = name.split(sep, 1)[0]
        out.add(name.strip().lower())
    return out


def _direct_dep_extras(project: dict, name: str) -> set[str]:
    """Return the set of extras requested for a given direct dep."""
    for entry in project["dependencies"]:
        head = entry.split("[", 1)[0]
        for sep in (">=", "<=", "==", "!=", "~=", ">", "<"):
            if sep in head:
                head = head.split(sep, 1)[0]
        if head.strip().lower() != name.lower():
            continue
        if "[" not in entry:
            return set()
        inside = entry.split("[", 1)[1].split("]", 1)[0]
        return {x.strip().lower() for x in inside.split(",")}
    return set()


def test_fastapi_not_a_direct_dep(project_table: dict) -> None:
    assert "fastapi" not in _direct_dep_names(project_table), (
        "fastapi has zero src/ imports and no dashboard v2 HTTP endpoint shipped; "
        "remove from [project].dependencies per PRD §6.12.T7."
    )


def test_uvicorn_not_a_direct_dep(project_table: dict) -> None:
    assert "uvicorn" not in _direct_dep_names(project_table), "uvicorn has zero src/ imports; remove per PRD §6.12.T7."


def test_pydantic_ai_mcp_extra_removed(project_table: dict) -> None:
    extras = _direct_dep_extras(project_table, "pydantic-ai")
    assert "mcp" not in extras, "No MCP usage in src/ per CLAUDE.md; remove [mcp] extra per PRD §6.12.T7."


def test_pydantic_ai_dbos_extra_removed(project_table: dict) -> None:
    extras = _direct_dep_extras(project_table, "pydantic-ai")
    assert "dbos" not in extras, (
        "DBOS confirmed disabled; ImportError-gated code paths remain. " "Remove [dbos] extra per PRD §6.12.T7."
    )


def test_defusedxml_kept_as_explicit_pin(project_table: dict) -> None:
    assert "defusedxml" in _direct_dep_names(project_table), (
        "Transitive consumer (py-serializable via cyclonedx via pip-audit) "
        "exists per uv tree; per PRD §6.12.T7 option (a), keep as explicit pin."
    )


def test_dbos_gated_imports_still_succeed() -> None:
    """The pipeline SDK + observability must import cleanly even without the
    pydantic-ai[dbos] extra installed. Both modules wrap DBOS imports in
    try/except, so removing the extra at the [project] level must not break
    cold-start imports."""
    importlib.import_module("academic_pipeline.sdk.pipeline")
    importlib.import_module("academic_pipeline.observability")
