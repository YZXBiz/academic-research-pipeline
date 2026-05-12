"""Tests for AST-based line tracer."""

from __future__ import annotations

import pytest

from academic_pipeline.experiment.line_tracer import extract_metric_lines


def test_simple_subscript_assign_with_double_quote_key() -> None:
    code = '''
results = {}
auc = 0.87
results["auc"] = auc
'''
    assert extract_metric_lines(code) == {"auc": 4}


def test_simple_subscript_assign_with_single_quote_key() -> None:
    code = '''
results = {}
results['f1'] = 0.72
'''
    assert extract_metric_lines(code) == {"f1": 3}


def test_last_assignment_wins_when_key_assigned_twice() -> None:
    code = '''
results = {}
results["auc"] = 0.5
# ... later overwrite ...
results["auc"] = 0.87
'''
    assert extract_metric_lines(code) == {"auc": 5}


def test_aug_assign_records_line() -> None:
    code = '''
results = {"count": 0}
results["count"] += 1
'''
    assert extract_metric_lines(code) == {"count": 3}


def test_dynamic_key_via_fstring_is_skipped() -> None:
    code = '''
results = {}
i = 0
results[f"fold_{i}_auc"] = 0.85
'''
    assert extract_metric_lines(code) == {}


def test_dict_update_call_not_traced() -> None:
    code = '''
results = {}
results.update({"a": 1, "b": 2})
'''
    assert extract_metric_lines(code) == {}


def test_empty_code_returns_empty_dict() -> None:
    assert extract_metric_lines("") == {}


def test_multi_line_rhs_records_first_line_of_assign() -> None:
    code = '''
results = {}
results["x"] = (
    1
    + 2
)
'''
    assert extract_metric_lines(code) == {"x": 3}


def test_syntax_error_propagates() -> None:
    with pytest.raises(SyntaxError):
        extract_metric_lines("results['x'] = (")


def test_custom_results_var_name() -> None:
    code = '''
metrics = {}
metrics["auc"] = 0.87
'''
    assert extract_metric_lines(code, results_var="metrics") == {"auc": 3}
    assert extract_metric_lines(code) == {}


def test_assignment_to_other_dict_var_not_traced() -> None:
    code = '''
results = {}
other = {}
other["ignored"] = 1
results["captured"] = 2
'''
    assert extract_metric_lines(code) == {"captured": 5}


def test_nested_function_with_local_results_dict_traced() -> None:
    code = '''
def compute():
    results = {}
    results["nested"] = 1
    return results
'''
    assert extract_metric_lines(code) == {"nested": 4}
