"""Lua filter rewrites pandoc Table blocks into IEEEtran-friendly table* env.

We invoke pandoc directly with the filter against a markdown fixture
and check the LaTeX output. Catches regressions where the filter is
silently a no-op (wrong AST node type) or rewrites the wrong block.
Skips on environments without pandoc installed (CI-safe).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


_FILTER = Path("templates/pandoc/longtable-to-table-star.lua")

_TABLE_MD = """\
| Algorithm | k | Silhouette |
|-----------|--:|-----------:|
| K-means   | 8 |      0.137 |
| Ward      | 8 |      0.135 |
| GMM       | 8 |      0.089 |
"""


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_filter_emits_table_star_not_longtable(tmp_path: Path) -> None:
    md = tmp_path / "in.md"
    md.write_text(_TABLE_MD)
    out = subprocess.run(
        ["pandoc", str(md), "-t", "latex", f"--lua-filter={_FILTER}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert r"\begin{table*}" in out.stdout, (
        "Filter must emit \\begin{table*} so the table spans both columns "
        f"under IEEEtran/conference. Got:\n{out.stdout}"
    )
    assert r"\begin{longtable}" not in out.stdout, (
        "Filter must REPLACE longtable, not coexist with it. "
        f"Got:\n{out.stdout}"
    )


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_filter_preserves_table_content(tmp_path: Path) -> None:
    md = tmp_path / "in.md"
    md.write_text(_TABLE_MD)
    out = subprocess.run(
        ["pandoc", str(md), "-t", "latex", f"--lua-filter={_FILTER}"],
        capture_output=True,
        text=True,
        check=True,
    )
    # Header + values must round-trip.
    for token in ("Algorithm", "K-means", "0.137", "Ward", "0.135"):
        assert token in out.stdout, f"Lost cell content {token!r}: {out.stdout}"
