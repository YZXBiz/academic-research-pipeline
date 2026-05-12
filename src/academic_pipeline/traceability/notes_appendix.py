r"""Notes appendix generator.

Emits LaTeX \section{Calculation Notes} listing every cited NumericalProduct
with its formula, context, and a hyperlink to the source code line in the
Code appendix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from academic_pipeline.models.numerical import NumericalStore


def _format_code_link(source_code_line: str | None, source_run_id: str) -> str:
    r"""Return a LaTeX hyperlink to the code appendix anchor for the source line."""
    if source_code_line is None:
        return ""
    # source_code_line format: "analysis.py:42" → anchor "code_<run>_42"
    line_num = source_code_line.rsplit(":", 1)[-1]
    anchor = f"code_{source_run_id}_{line_num}"
    return rf" See \hyperlink{{{anchor}}}{{{source_code_line}}}."


def generate_notes_appendix(store: NumericalStore, cited_labels: set[str]) -> str:
    r"""Emit LaTeX Calculation Notes appendix with one entry per cited label.

    Returns empty string if no labels cited (caller should not include the section).
    """
    if not cited_labels:
        return ""
    items: list[str] = []
    for label in sorted(cited_labels):
        if label not in store.products:
            continue
        p = store.products[label]
        unit_str = f" {p.unit}" if p.unit else ""
        code_link = _format_code_link(p.source_code_line, p.source_run_id)
        items.append(
            rf"\item \hypertarget{{num_{label}}}{{}}"
            rf"\textbf{{{p.value}{unit_str}}} --- {p.context}. "
            rf"Computed as: {p.formula}.{code_link}"
        )
    body = "\n".join(items)
    return r"\section{Calculation Notes}" + "\n" + r"\begin{itemize}" + "\n" + body + "\n" + r"\end{itemize}"
