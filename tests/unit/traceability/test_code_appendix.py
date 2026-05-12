"""Tests for generate_code_appendix."""

from __future__ import annotations

from dataclasses import dataclass

from academic_pipeline.traceability.code_appendix import generate_code_appendix


@dataclass(frozen=True)
class StubCodeRun:
    """Stand-in for a real ExperimentRun-like type. The implementer should check
    `src/academic_pipeline/models/experiment.py` for an existing type with
    matching attributes and use it instead if one exists. The Protocol in
    code_appendix.py is structural so any type with run_id / code / code_filename
    / producing_lines attributes will work."""
    run_id: str
    code: str
    code_filename: str
    producing_lines: tuple[int, ...]


def test_appendix_emits_section_per_run() -> None:
    runs = [StubCodeRun(run_id="r1", code="a = 1\nb = 2\n", code_filename="x.py", producing_lines=(2,))]
    out = generate_code_appendix(runs)
    assert r"\section{Code: x.py}" in out


def test_appendix_inserts_hypertarget_at_producing_line() -> None:
    runs = [StubCodeRun(run_id="r1", code="a = 1\nb = 2\nc = 3\n", code_filename="x.py", producing_lines=(2,))]
    out = generate_code_appendix(runs)
    # The hypertarget must be on line 2, alongside `b = 2`
    assert r"\hypertarget{code_r1_2}{}" in out
    assert "b = 2" in out


def test_appendix_handles_multiple_producing_lines() -> None:
    runs = [StubCodeRun(run_id="r1", code="a\nb\nc\n", code_filename="x.py", producing_lines=(1, 3))]
    out = generate_code_appendix(runs)
    assert r"\hypertarget{code_r1_1}{}" in out
    assert r"\hypertarget{code_r1_3}{}" in out


def test_appendix_handles_multiple_runs() -> None:
    runs = [
        StubCodeRun(run_id="r1", code="a\n", code_filename="x.py", producing_lines=(1,)),
        StubCodeRun(run_id="r2", code="b\n", code_filename="y.py", producing_lines=(1,)),
    ]
    out = generate_code_appendix(runs)
    assert r"\section{Code: x.py}" in out
    assert r"\section{Code: y.py}" in out
    assert r"\hypertarget{code_r1_1}" in out
    assert r"\hypertarget{code_r2_1}" in out


def test_appendix_empty_for_no_runs() -> None:
    out = generate_code_appendix([])
    assert out == ""


def test_appendix_empty_producing_lines_renders_code_without_hypertargets() -> None:
    """Code that produced no traced numbers still appears in appendix, just without anchors."""
    runs = [StubCodeRun(run_id="r1", code="import sys\n", code_filename="x.py", producing_lines=())]
    out = generate_code_appendix(runs)
    assert r"\section{Code: x.py}" in out
    assert "import sys" in out
    assert r"\hypertarget" not in out
