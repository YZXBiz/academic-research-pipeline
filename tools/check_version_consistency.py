"""Check that VERSION, pyproject.toml::version, and README.md badges agree.

Usage: `uv run python tools/check_version_consistency.py`

Exits 0 with no output when the three sources match.
Exits 1 with a CIR001 (PyprojectVersionDrift) diagnostic on stderr otherwise.

Wired into `make check` per PRD §6.12.T6 + §6.14.T3.
Error code namespace: PRD §17 CIR000-CIR099.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_FILE = "VERSION"
PYPROJECT_FILE = "pyproject.toml"
README_FILE = "README.md"

# Matches both `badge/version-vX.Y.Z-...` and `alt="vX.Y.Z"` forms.
README_BADGE_RE = re.compile(r"badge/version-v(\d+\.\d+\.\d+)")
README_ALT_RE = re.compile(r'alt="v(\d+\.\d+\.\d+)"')


def _read_version_file(root: Path) -> str:
    return (root / VERSION_FILE).read_text().strip()


def _read_pyproject_version(root: Path) -> str:
    data = tomllib.loads((root / PYPROJECT_FILE).read_text())
    return str(data["project"]["version"])


def _read_readme_versions(root: Path) -> set[str]:
    text = (root / README_FILE).read_text()
    found = set(README_BADGE_RE.findall(text)) | set(README_ALT_RE.findall(text))
    return found


def main(root: Path | None = None) -> int:
    """Run the version-consistency check; return process exit code."""
    root = root or Path.cwd()

    missing: list[str] = [name for name in (VERSION_FILE, PYPROJECT_FILE, README_FILE) if not (root / name).is_file()]
    if missing:
        print(
            f"CIR001 PyprojectVersionDrift: missing source file(s): {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    version_file_value = _read_version_file(root)
    pyproject_value = _read_pyproject_version(root)
    readme_values = _read_readme_versions(root)

    diagnostics: list[str] = []
    if not readme_values:
        diagnostics.append(f"README.md: no version badge matched pattern " f"{README_BADGE_RE.pattern!r}")
    elif len(readme_values) > 1:
        diagnostics.append(f"README.md: badges disagree internally: {sorted(readme_values)}")
    if version_file_value != pyproject_value:
        diagnostics.append(
            f"VERSION={version_file_value!r} disagrees with " f"pyproject.toml::version={pyproject_value!r}"
        )
    if readme_values and len(readme_values) == 1:
        readme_value = next(iter(readme_values))
        if readme_value != version_file_value or readme_value != pyproject_value:
            diagnostics.append(
                f"README.md badge=v{readme_value} disagrees with "
                f"VERSION={version_file_value!r} / pyproject.toml::version={pyproject_value!r}"
            )

    if diagnostics:
        for d in diagnostics:
            print(f"CIR001 PyprojectVersionDrift: {d}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
