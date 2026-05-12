"""Tests for the §6.7.T3 ``LatexCompilerNode`` authors.yaml gate.

The node MUST refuse to start a compile when no ``authors.yaml`` is
findable via ``resolve_authors_yaml_path``. Instead of running pandoc
and emitting a 'Author, Affiliation TBD' PDF, the node raises
``AuthorsYamlMissing`` (REN002).

Tests use static-source inspection plus a real-graph dispatch with a
patched resolver — that's the same pattern existing
``test_latex_compiler_copies_figures.py`` uses for compile-side asserts
without spawning pandoc.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.anyio


def test_latex_compiler_node_invokes_authors_gate() -> None:
    """Static check: node body wires the loader + resolver.

    Catches accidental removal of the gate during future refactors —
    cheaper than spinning up the full graph on every run.
    """
    from academic_pipeline.writing import graph as wg

    src = inspect.getsource(wg.LatexCompilerNode)
    assert "load_authors_yaml" in src, (
        "LatexCompilerNode.run() must call load_authors_yaml as part of " "the §6.7.T3 build gate."
    )
    assert "resolve_authors_yaml_path" in src, (
        "LatexCompilerNode.run() must call resolve_authors_yaml_path so the "
        "operator's run_dir / repo_root override beats the cwd default."
    )


async def test_node_raises_REN002_when_authors_yaml_absent(  # noqa: N802 — REN001/REN002 are PRD §17 codes
    tmp_path: Path,
) -> None:
    """End-to-end: with no authors.yaml anywhere on the resolver path,
    ``LatexCompilerNode.run`` raises ``AuthorsYamlMissing`` BEFORE it
    invokes pandoc."""
    from academic_pipeline.runtime.rendering_errors import AuthorsYamlMissing
    from academic_pipeline.writing.graph import LatexCompilerNode

    state = MagicMock()
    state.bib_source = ""
    state.paper_draft = None
    state.formatted_output = {"formatted_content": "# t"}
    state.figure_package = None
    state.numerical_store = None
    state.experiment_results = None
    state.messages = []
    deps = MagicMock()
    deps.config.traceability_mode = "off"
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    # Force the resolver to find nothing → the gate must short-circuit.
    with (
        patch(
            "academic_pipeline.runtime.authors_yaml.resolve_authors_yaml_path",
            return_value=None,
        ),
        pytest.raises(AuthorsYamlMissing) as exc,
    ):
        await LatexCompilerNode().run(ctx)

    assert exc.value.error_code == "REN002"


async def test_node_passes_when_authors_yaml_resolves(
    tmp_path: Path,
) -> None:
    """When ``resolve_authors_yaml_path`` returns a valid file, the gate
    accepts it and we hand control over to compile_pdf_pandoc (which we
    stub so we don't actually shell out to pandoc)."""
    from academic_pipeline.writing.graph import LatexCompilerNode

    authors_path = tmp_path / "authors.yaml"
    authors_path.write_text(
        "- name: Jackson Yang\n  affiliation: Example Institute\n",
        encoding="utf-8",
    )

    state = MagicMock()
    state.bib_source = ""
    state.paper_draft = None
    state.formatted_output = {"formatted_content": "# t"}
    state.figure_package = None
    state.numerical_store = None
    state.experiment_results = None
    state.messages = []
    deps = MagicMock()
    deps.config.traceability_mode = "off"
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    async def _stub_compile(*_a: object, **_kw: object) -> None:
        # Returns None like a failed pandoc invocation. Importantly: NO exception.
        return None

    with (
        patch(
            "academic_pipeline.runtime.authors_yaml.resolve_authors_yaml_path",
            return_value=authors_path,
        ),
        patch(
            "academic_pipeline.tools.rendering.latex_compiler.compile_pdf_pandoc",
            new=_stub_compile,
        ),
    ):
        result = await LatexCompilerNode().run(ctx)

    # End[str] is what LatexCompilerNode returns. The point is: no exception.
    assert result is not None
