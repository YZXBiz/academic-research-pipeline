"""Tests for line-level provenance integration in extract_numerical_products_from_result."""

from __future__ import annotations

from academic_pipeline.experiment.producers import extract_numerical_products_from_result
from academic_pipeline.models.experiment import ExperimentResults


def _make_results(metrics: dict, code: str = "") -> ExperimentResults:
    """Construct an ExperimentResults with the minimum fields the producer reads."""
    return ExperimentResults(
        code=code,
        metrics=metrics,
        figures=[],
        stdout="",
        stderr="",
    )


def test_producer_without_code_kwarg_keeps_source_code_line_none() -> None:
    """Backward compat: existing callers (without code) get current behavior."""
    results = _make_results(metrics={"xgboost": {"auc": 0.87}})
    products = extract_numerical_products_from_result(
        result=results, run_id="r1", source_step="experiment.analysis",
    )
    assert len(products) == 1
    assert products[0].source_code_line is None


def test_producer_with_code_populates_source_code_line() -> None:
    """When code matches the metric label, source_code_line is "<filename>:<lineno>"."""
    code = '''
results = {}
results["auc"] = 0.87
'''
    results = _make_results(metrics={"xgboost": {"auc": 0.87}}, code=code)
    products = extract_numerical_products_from_result(
        result=results, run_id="r1", source_step="experiment.analysis",
        code=code, code_filename="analysis.py",
    )
    assert len(products) == 1
    # Composite label is "xgboost__auc"; line tracer returned {"auc": 3}
    # Producer should fall back from composite to raw label
    assert products[0].source_code_line == "analysis.py:3"


def test_producer_prefers_composite_label_over_raw_when_both_exist_in_code() -> None:
    """If the script writes to the composite label directly, prefer that line."""
    code = '''
results = {}
results["auc"] = 0.5
results["xgboost__auc"] = 0.87
'''
    results = _make_results(metrics={"xgboost": {"auc": 0.87}}, code=code)
    products = extract_numerical_products_from_result(
        result=results, run_id="r1", source_step="experiment.analysis",
        code=code, code_filename="analysis.py",
    )
    # Composite "xgboost__auc" found at line 4 — preferred over raw "auc" at line 3
    assert products[0].source_code_line == "analysis.py:4"


def test_producer_with_unparseable_code_degrades_gracefully() -> None:
    """SyntaxError in code → all source_code_line stay None, no crash."""
    bad_code = "this is not python code !!!"
    results = _make_results(metrics={"xgboost": {"auc": 0.87}}, code=bad_code)
    products = extract_numerical_products_from_result(
        result=results, run_id="r1", source_step="experiment.analysis",
        code=bad_code, code_filename="analysis.py",
    )
    assert len(products) == 1
    assert products[0].source_code_line is None  # graceful degradation


def test_producer_with_code_but_label_not_in_ast_keeps_source_code_line_none() -> None:
    """Metric assigned via dynamic key (f-string) → source_code_line stays None."""
    code = '''
results = {}
fold = 0
results[f"xgboost__fold_{fold}__auc"] = 0.87
'''
    results = _make_results(
        metrics={"xgboost": {"fold_0__auc": 0.87}}, code=code,
    )
    products = extract_numerical_products_from_result(
        result=results, run_id="r1", source_step="experiment.analysis",
        code=code, code_filename="analysis.py",
    )
    assert len(products) == 1
    assert products[0].source_code_line is None


def test_producer_with_default_code_filename_when_none_passed() -> None:
    """If code_filename is None but code is supplied, use 'analysis.py' as default."""
    code = 'results = {}\nresults["auc"] = 0.87\n'
    results = _make_results(metrics={"xgboost": {"auc": 0.87}}, code=code)
    products = extract_numerical_products_from_result(
        result=results, run_id="r1", source_step="experiment.analysis",
        code=code, code_filename=None,
    )
    assert products[0].source_code_line == "analysis.py:2"
