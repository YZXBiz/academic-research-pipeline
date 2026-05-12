"""LatexCompilerNode must copy figure PNGs into build_dir/figures/, NOT
execute the figure_executor sandbox (retired by figures-via-dagster pivot).
"""
from __future__ import annotations

import inspect
import re

from academic_pipeline.writing import graph as wg


def test_latex_compiler_copies_figures_into_build_dir() -> None:
    """LatexCompilerNode must use shutil.copy to place each figure's
    source_path PNG into build_dir/figures/."""
    src = inspect.getsource(wg.LatexCompilerNode)
    assert "shutil.copy" in src, (
        "LatexCompilerNode.run() must use shutil.copy() to place each figure's "
        "source_path PNG into build_dir/figures/."
    )
    assert "figures" in src, (
        "LatexCompilerNode must reference the figures/ subdir of build_dir."
    )


def test_latex_compiler_does_not_call_execute_figures() -> None:
    """Defensive: figures-via-dagster pivot retired execute_figures."""
    src = inspect.getsource(wg.LatexCompilerNode)
    assert "execute_figures" not in src, (
        "LatexCompilerNode must not call execute_figures — sandbox runner retired."
    )


def test_writing_graph_imports_shutil_at_module_top() -> None:
    """Per project code standards: imports at module top, not inline."""
    src = inspect.getsource(wg)
    head = src.split("\nclass ", 1)[0]
    assert re.search(r"^import shutil$", head, re.MULTILINE), (
        "shutil must be imported at the module top (not inside a function/class body)."
    )
