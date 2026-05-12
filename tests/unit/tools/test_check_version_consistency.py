"""Tests for tools/check_version_consistency.py (PRD §6.12.T6).

The script must:
1. Read VERSION (file at repo root).
2. Read pyproject.toml::version (TOML key).
3. Read README.md badge versions (img.shields.io/badge/version-v<X>-... and alt).
4. Exit 0 with no output on stdout when all three agree (case sensitivity:
   VERSION + pyproject use bare "X.Y.Z"; README badge uses "vX.Y.Z").
5. Exit 1 with a diagnostic on stderr that names every mismatching source
   when they disagree.

Diagnostic uses error namespace CIR (PRD §17). Specifically CIR001
PyprojectVersionDrift covers the version-drift case.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "check_version_consistency.py"


def _run(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _make_repo(
    tmp_path: Path,
    *,
    version_file: str,
    pyproject_version: str,
    readme_badge_version: str,
) -> Path:
    (tmp_path / "VERSION").write_text(version_file)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{pyproject_version}"\n')
    badge = (
        f'<img src="https://img.shields.io/badge/version-v{readme_badge_version}-blue" '
        f'alt="v{readme_badge_version}">\n'
        f"some text mentioning v{readme_badge_version}\n"
    )
    (tmp_path / "README.md").write_text(badge)
    return tmp_path


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"script must exist at {SCRIPT}"


def test_passes_when_all_three_agree(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        version_file="2.5.0\n",
        pyproject_version="2.5.0",
        readme_badge_version="2.5.0",
    )
    result = _run(tmp_path)
    assert (
        result.returncode == 0
    ), f"expected exit 0; got {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"


def test_fails_when_pyproject_drifts(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        version_file="2.5.0\n",
        pyproject_version="0.2.0",
        readme_badge_version="2.5.0",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "pyproject" in result.stderr.lower()
    assert "CIR001" in result.stderr


def test_fails_when_version_file_drifts(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        version_file="2.3.0\n",
        pyproject_version="2.5.0",
        readme_badge_version="2.5.0",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "VERSION" in result.stderr
    assert "CIR001" in result.stderr


def test_fails_when_readme_badge_drifts(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        version_file="2.5.0\n",
        pyproject_version="2.5.0",
        readme_badge_version="2.3.0",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "README" in result.stderr
    assert "CIR001" in result.stderr


def test_repo_itself_is_consistent() -> None:
    """The actual repo must pass the check after this task lands."""
    result = _run(REPO_ROOT)
    assert result.returncode == 0, f"repo version drift detected:\nstdout={result.stdout}\nstderr={result.stderr}"


@pytest.mark.parametrize(
    "missing",
    ["VERSION", "pyproject.toml", "README.md"],
)
def test_fails_when_source_missing(tmp_path: Path, missing: str) -> None:
    _make_repo(
        tmp_path,
        version_file="2.5.0\n",
        pyproject_version="2.5.0",
        readme_badge_version="2.5.0",
    )
    (tmp_path / missing).unlink()
    result = _run(tmp_path)
    assert result.returncode == 1
    assert missing in result.stderr
