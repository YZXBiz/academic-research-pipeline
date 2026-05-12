r"""Code appendix generator with hypertargets at producing code lines.

Each NumericalProduct's source_code_line points to a line in this appendix.
The Notes appendix entries link to these hypertargets for clickable trace.

Uses a structural Protocol for the run input so any type with the matching
attributes works (StubCodeRun in tests, ExperimentRun in production).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from collections.abc import Iterable


class _CodeRun(Protocol):
    """Structural type for a code run that produced traced numbers."""
    run_id: str
    code: str
    code_filename: str
    producing_lines: tuple[int, ...]


def _inject_hypertargets(code: str, run_id: str, lines: Iterable[int]) -> str:
    code_lines = code.split("\n")
    line_set = set(lines)
    out_lines: list[str] = []
    for idx, line in enumerate(code_lines, start=1):
        if idx in line_set:
            out_lines.append(rf"\hypertarget{{code_{run_id}_{idx}}}{{}}{line}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def generate_code_appendix(runs: Iterable[_CodeRun]) -> str:
    """Emit LaTeX appendix sections — one per code run — with hypertargets at producing lines.

    Returns empty string if no runs (caller should not include the section).
    """
    sections: list[str] = []
    for run in runs:
        body = _inject_hypertargets(run.code, run.run_id, run.producing_lines)
        sections.append(
            rf"\section{{Code: {run.code_filename}}}" + "\n" +
            r"\begin{python}" + "\n" + body + "\n" + r"\end{python}"
        )
    return "\n\n".join(sections)
