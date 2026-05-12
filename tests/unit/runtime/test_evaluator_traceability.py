"""Tests for traceability_context plumbing in evaluator.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_evaluate_node_output_no_traceability_context_unchanged() -> None:
    """When traceability_context is None, _run_single_evaluator gets 3 positional args (model, output_json, rubric)."""
    from academic_pipeline.config import PipelineConfig
    from academic_pipeline.models.shared import EvaluationResult
    from academic_pipeline.core.deps import PipelineDeps
    from academic_pipeline.runtime.evaluator import evaluate_node_output

    deps = PipelineDeps.create(config=PipelineConfig(
        anthropic_api_key="sk-test",  # type: ignore[arg-type]
        model_name="test",
        evaluator_models=["anthropic:claude-opus-4-7"],
    ))
    deps.config.enable_node_evaluation = True

    fake_eval = EvaluationResult(
        verdict="PASS", scores={"depth": 8.0}, feedback="ok",
        weakest_dimension=None,
    )

    with patch(
        "academic_pipeline.runtime.evaluator._run_single_evaluator",
        new=AsyncMock(return_value=fake_eval),
    ) as mock_run:
        await evaluate_node_output(
            output_json='{"x": 1}',
            rubric="Score: PASS if good.",
            deps=deps,
        )

    args = mock_run.call_args.args
    # Either 3 args (no traceability) or 4 args with last being None
    if len(args) == 4:
        assert args[3] is None, "When None traceability passed, value must be None"
    else:
        assert len(args) == 3


@pytest.mark.asyncio
async def test_evaluate_node_output_traceability_context_prepended() -> None:
    """When traceability_context is provided, _run_single_evaluator gets it as a 4th arg."""
    from academic_pipeline.config import PipelineConfig
    from academic_pipeline.models.shared import EvaluationResult
    from academic_pipeline.core.deps import PipelineDeps
    from academic_pipeline.runtime.evaluator import evaluate_node_output

    deps = PipelineDeps.create(config=PipelineConfig(
        anthropic_api_key="sk-test",  # type: ignore[arg-type]
        model_name="test",
        evaluator_models=["anthropic:claude-opus-4-7"],
    ))
    deps.config.enable_node_evaluation = True

    fake_eval = EvaluationResult(
        verdict="PASS", scores={"depth": 8.0}, feedback="ok",
        weakest_dimension=None,
    )

    upstream = "## SYNTHESIS\nQuantitative pooling awaits the full search."

    with patch(
        "academic_pipeline.runtime.evaluator._run_single_evaluator",
        new=AsyncMock(return_value=fake_eval),
    ) as mock_run:
        await evaluate_node_output(
            output_json='{"x": 1}',
            rubric="Score: PASS if good.",
            deps=deps,
            traceability_context=upstream,
        )

    args = mock_run.call_args.args
    assert len(args) == 4
    assert args[3] == upstream


@pytest.mark.asyncio
async def test_run_single_evaluator_includes_traceability_in_prompt() -> None:
    """When traceability_context is non-empty, the agent.run prompt MUST include
    a TRACEABILITY CONTEXT header before the rubric."""
    from academic_pipeline.runtime.evaluator import _run_single_evaluator

    fake_result = MagicMock()
    fake_result.output = MagicMock()
    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(return_value=fake_result)

    with patch("academic_pipeline.runtime.evaluator._get_evaluator_agent", return_value=fake_agent):
        await _run_single_evaluator(
            model_name="anthropic:claude-opus-4-7",
            output_json='{"x":1}',
            rubric="r",
            traceability_context="upstream content",
        )

    prompt_arg = fake_agent.run.call_args.args[0]
    assert "TRACEABILITY CONTEXT" in prompt_arg
    assert "upstream content" in prompt_arg
    assert prompt_arg.index("TRACEABILITY CONTEXT") < prompt_arg.index("Rubric:")


@pytest.mark.asyncio
async def test_run_single_evaluator_omits_traceability_when_none() -> None:
    """When traceability_context is None, the prompt MUST NOT include the header."""
    from academic_pipeline.runtime.evaluator import _run_single_evaluator

    fake_result = MagicMock()
    fake_result.output = MagicMock()
    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(return_value=fake_result)

    with patch("academic_pipeline.runtime.evaluator._get_evaluator_agent", return_value=fake_agent):
        await _run_single_evaluator(
            model_name="anthropic:claude-opus-4-7",
            output_json='{"x":1}',
            rubric="r",
            traceability_context=None,
        )

    prompt_arg = fake_agent.run.call_args.args[0]
    assert "TRACEABILITY CONTEXT" not in prompt_arg


@pytest.mark.asyncio
async def test_run_with_evaluation_passes_traceability_to_eval(tmp_path) -> None:
    """run_with_evaluation forwards traceability_context to evaluate_node_output."""
    from academic_pipeline.config import PipelineConfig
    from academic_pipeline.models.shared import EvaluationResult
    from academic_pipeline.core.deps import PipelineDeps
    from academic_pipeline.runtime.evaluator import run_with_evaluation

    deps = PipelineDeps.create(config=PipelineConfig(
        anthropic_api_key="sk-test",  # type: ignore[arg-type]
        model_name="test",
        evaluator_models=["anthropic:claude-opus-4-7"],
    ))
    deps.config.enable_node_evaluation = True

    fake_agent_result = MagicMock()
    fake_agent_result.output = MagicMock()
    fake_agent_result.output.model_dump_json = lambda: '{"x":1}'
    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(return_value=fake_agent_result)

    fake_eval = EvaluationResult(
        verdict="PASS", scores={"depth": 8.0}, feedback="ok",
        weakest_dimension=None,
    )

    with patch(
        "academic_pipeline.runtime.evaluator.evaluate_node_output",
        new=AsyncMock(return_value=fake_eval),
    ) as mock_eval:
        await run_with_evaluation(
            agent=fake_agent,
            context="ctx",
            rubric="r",
            deps=deps,
            traceability_context="upstream stuff",
            name="test_node",
            phase="test",
        )

    eval_kwargs = mock_eval.call_args.kwargs
    assert eval_kwargs.get("traceability_context") == "upstream stuff"
