"""AST-based line tracer for experiment-result provenance.

Walks an executed script's AST to find lines that write to the results dict,
returning {label -> 1-indexed line number}. Used by experiment/producers.py to
populate NumericalProduct.source_code_line.

Supports the dominant pattern in this pipeline (AutoGluon templates):
    results["auc"] = ...
    results['auc'] = ...
    results["pct_high"] = expr.method()
    results["count"] += 1                    # AugAssign

Does NOT support (returns no entry -> caller degrades to source_code_line=None):
    results[f"fold_{i}_auc"] = ...           # dynamic key (f-string)
    for k, v in pairs: results[k] = v        # dynamic key (loop var)
    results.update({"a": 1, "b": 2})         # dict.update call

If a key is assigned multiple times, the LAST assignment wins (matches reader
intuition: the value at the end of execution came from the last write).

Raises SyntaxError if the code doesn't parse — caller catches + logs + skips.
"""

from __future__ import annotations

import ast


def extract_metric_lines(code: str, results_var: str = "results") -> dict[str, int]:
    """Walk the AST of `code` and return {label -> 1-indexed line_number}."""
    if not code.strip():
        return {}
    tree = ast.parse(code)
    last_line: dict[str, int] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _record_subscript_assign(target, node.lineno, results_var, last_line)
        elif isinstance(node, ast.AugAssign):
            _record_subscript_assign(node.target, node.lineno, results_var, last_line)

    return last_line


def _record_subscript_assign(
    target: ast.expr,
    lineno: int,
    results_var: str,
    out: dict[str, int],
) -> None:
    """If target is `results_var["literal_string"]`, record line number."""
    if not isinstance(target, ast.Subscript):
        return
    if not isinstance(target.value, ast.Name) or target.value.id != results_var:
        return
    slice_node = target.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        out[slice_node.value] = lineno
