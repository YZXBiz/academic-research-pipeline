"""FunctionModel-based tests for evaluator scoring logic.

Uses FunctionModel to return specific EvaluationResult JSON,
testing aggregation (median, conservative min), failure fallback,
and rubber-stamp detection deterministically.
"""

from __future__ import annotations

import json
import logging

import pytest
from pydantic_ai.messages import TextPart
from pydantic_ai.models import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from academic_pipeline.models.shared import EvaluationResult
from academic_pipeline.runtime.evaluator import _aggregate_results, _get_evaluator_agent


def _make_eval_json(
    verdict: str = "PASS",
    scores: dict[str, float] | None = None,
    feedback: str = "Good.",
    weakest: str | None = None,
) -> str:
    scores = scores or {"quality": 8.0, "depth": 7.5}
    return json.dumps({
        "verdict": verdict,
        "scores": scores,
        "feedback": feedback,
        "weakest_dimension": weakest,
    })


def test_three_evaluator_median_scoring():
    """With 3 evaluators, median is used (not mean, not min)."""
    pairs = [
        ("model_a", EvaluationResult(verdict="PASS", scores={"quality": 6.0, "depth": 8.0}, feedback="A")),
        ("model_b", EvaluationResult(verdict="PASS", scores={"quality": 8.0, "depth": 7.0}, feedback="B")),
        ("model_c", EvaluationResult(verdict="PASS", scores={"quality": 9.0, "depth": 9.0}, feedback="C")),
    ]
    result = _aggregate_results(pairs, threshold=7.0)
    assert result.scores["quality"] == 8.0  # median of 6, 8, 9
    assert result.scores["depth"] == 8.0  # median of 8, 7, 9


def test_two_evaluator_conservative_min():
    """With 2 evaluators, min is used (conservative to prevent Gemini inflation)."""
    pairs = [
        ("model_a", EvaluationResult(verdict="PASS", scores={"quality": 9.5, "depth": 9.0}, feedback="Inflated")),
        ("model_b", EvaluationResult(verdict="PASS", scores={"quality": 7.0, "depth": 6.5}, feedback="Strict")),
    ]
    result = _aggregate_results(pairs, threshold=7.0)
    assert result.scores["quality"] == 7.0  # min of 9.5, 7.0
    assert result.scores["depth"] == 6.5  # min of 9.0, 6.5
    assert result.verdict == "NEEDS_IMPROVEMENT"  # depth 6.5 < 7.0 threshold


def test_threshold_boundary():
    """Score exactly at threshold should PASS."""
    pairs = [
        ("model_a", EvaluationResult(verdict="PASS", scores={"quality": 7.0}, feedback="OK")),
        ("model_b", EvaluationResult(verdict="PASS", scores={"quality": 7.0}, feedback="OK")),
        ("model_c", EvaluationResult(verdict="PASS", scores={"quality": 7.0}, feedback="OK")),
    ]
    result = _aggregate_results(pairs, threshold=7.0)
    assert result.verdict == "PASS"


def test_rubber_stamp_warning(caplog: pytest.LogCaptureFixture):
    """Evaluator giving all scores >= 9.5 triggers rubber-stamp warning."""
    with caplog.at_level(logging.WARNING, logger="academic_pipeline.runtime.evaluator"):
        pairs = [
            ("inflated_model", EvaluationResult(verdict="PASS", scores={"a": 10.0, "b": 9.5}, feedback="Perfect")),
            ("normal_model", EvaluationResult(verdict="PASS", scores={"a": 7.0, "b": 7.5}, feedback="OK")),
        ]
        _aggregate_results(pairs, threshold=7.0)
    assert any("rubber-stamp" in r.message.lower() for r in caplog.records)


@pytest.mark.anyio
async def test_evaluator_agent_with_function_model():
    """FunctionModel returns specific EvaluationResult JSON."""
    eval_json = _make_eval_json(
        verdict="NEEDS_IMPROVEMENT",
        scores={"clarity": 5.0, "rigor": 6.0},
        feedback="Needs more rigor.",
        weakest="clarity",
    )

    def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=eval_json)])

    # Use a real provider prefix so _get_evaluator_agent can create the agent,
    # then override with FunctionModel for deterministic output.
    agent = _get_evaluator_agent("anthropic:claude-opus-4-7")
    with agent.override(model=FunctionModel(model_fn)):
        result = await agent.run("Rubric: test\n\nOutput: test")
        assert result.output.verdict == "NEEDS_IMPROVEMENT"
        assert result.output.scores["clarity"] == 5.0
        assert result.output.weakest_dimension == "clarity"
