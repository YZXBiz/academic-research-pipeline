"""Tests for evaluator fixes."""
from __future__ import annotations
import logging
from academic_pipeline.models.shared import EvaluationResult
from academic_pipeline.runtime.evaluator import _aggregate_results

def test_three_evaluators_uses_median():
    pairs = [
        ("anthropic:claude-opus-4-7", EvaluationResult(verdict="PASS", scores={"quality": 7.0}, feedback="ok")),
        ("gemini", EvaluationResult(verdict="PASS", scores={"quality": 10.0}, feedback="perfect")),
        ("claude", EvaluationResult(verdict="PASS", scores={"quality": 8.0}, feedback="good")),
    ]
    result = _aggregate_results(pairs, threshold=7.0)
    assert result.scores["quality"] == 8.0

def test_two_evaluators_uses_conservative_lower():
    pairs = [
        ("gemini", EvaluationResult(verdict="PASS", scores={"quality": 10.0}, feedback="perfect")),
        ("claude", EvaluationResult(verdict="PASS", scores={"quality": 7.0}, feedback="ok")),
    ]
    result = _aggregate_results(pairs, threshold=7.0)
    assert result.scores["quality"] == 7.0

def test_rubber_stamp_warning_logged(caplog):
    pairs = [
        ("gemini", EvaluationResult(verdict="PASS", scores={"a": 10.0, "b": 10.0, "c": 10.0}, feedback="")),
        ("gpt", EvaluationResult(verdict="PASS", scores={"a": 8.0, "b": 7.0, "c": 8.0}, feedback="")),
        ("claude", EvaluationResult(verdict="PASS", scores={"a": 9.0, "b": 8.0, "c": 9.0}, feedback="")),
    ]
    with caplog.at_level(logging.WARNING):
        _aggregate_results(pairs, threshold=7.0)
    assert any("rubber-stamp" in r.message.lower() or "9.5" in r.message for r in caplog.records)
