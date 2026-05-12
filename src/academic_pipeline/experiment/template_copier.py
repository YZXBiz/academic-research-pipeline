"""Copies templates/dagster-experiment/ into a workspace dir.

Excludes test fixtures, venvs, caches, and the lockfile (each workspace gets a
fresh `uv sync` against the template's pyproject.toml)."""
from __future__ import annotations

import shutil
from pathlib import Path


_TEMPLATE_NAME = "dagster-experiment"
_EXCLUDE_DIRS = {
    "tests",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".dagster",
    ".dg",
    "htmlcov",
    ".ruff_cache",
}
_EXCLUDE_FILES = {"uv.lock", ".coverage"}


def copy_template_into(workspace: Path, repo_root: Path | None = None) -> Path:
    """Copy templates/<_TEMPLATE_NAME>/ contents → workspace/. Returns workspace path.

    workspace must already exist (caller controls that)."""
    repo_root = repo_root or _find_repo_root()
    src = repo_root / "templates" / _TEMPLATE_NAME
    if not src.exists():
        raise FileNotFoundError(f"Template not found at {src}")

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in _EXCLUDE_DIRS or n in _EXCLUDE_FILES}

    for item in src.iterdir():
        if item.name in _EXCLUDE_DIRS or item.name in _EXCLUDE_FILES:
            continue
        target = workspace / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=_ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    return workspace


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "templates" / _TEMPLATE_NAME).exists():
            return p
    raise FileNotFoundError("Could not locate templates/dagster-experiment from package")
