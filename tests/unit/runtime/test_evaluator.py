from __future__ import annotations

import contextlib

import pytest
from pydantic_ai.models.test import TestModel

from academic_pipeline.runtime.evaluator import (
    _get_evaluator_agent,
    evaluate_node_output,
    run_with_evaluation,
)
from tests.conftest import make_test_deps


pytestmark = pytest.mark.anyio

SAMPLE_RUBRIC = """Evaluate this research question:
- Specificity (0-10): Is it precise enough?
- Feasibility (0-10): Can it be answered?
PASS if all >= 7. Otherwise NEEDS_IMPROVEMENT with feedback."""

PASS_EVAL_JSON = (
    '{"verdict": "PASS", "scores": {"specificity": 8.0, "feasibility": 9.0},'
    ' "feedback": "Good.", "weakest_dimension": null}'
)
FAIL_EVAL_JSON = (
    '{"verdict": "NEEDS_IMPROVEMENT", "scores": {"specificity": 5.0, "feasibility": 9.0},'
    ' "feedback": "Too vague.", "weakest_dimension": "specificity"}'
)


def _override_evaluators(output_json: str, models: list[str]):
    """Override all evaluator agents with TestModel returning given JSON."""
    stack = contextlib.ExitStack()
    for model_name in models:
        agent = _get_evaluator_agent(model_name)
        stack.enter_context(
            agent.override(model=TestModel(custom_output_text=output_json, call_tools=[]))
        )
    return stack


async def test_evaluate_node_output_returns_pass():
    deps = make_test_deps()
    deps.config = deps.config.model_copy(
        update={"evaluator_models": ["test"], "enable_node_evaluation": True}
    )
    with _override_evaluators(PASS_EVAL_JSON, ["test"]):
        result = await evaluate_node_output(
            output_json='{"research_question": "What is AI?"}',
            rubric=SAMPLE_RUBRIC,
            deps=deps,
        )
    assert result.verdict == "PASS"


async def test_evaluate_node_output_returns_needs_improvement():
    deps = make_test_deps()
    deps.config = deps.config.model_copy(
        update={"evaluator_models": ["test"], "enable_node_evaluation": True}
    )
    with _override_evaluators(FAIL_EVAL_JSON, ["test"]):
        result = await evaluate_node_output(
            output_json='{"research_question": "What is AI?"}',
            rubric=SAMPLE_RUBRIC,
            deps=deps,
        )
    assert result.verdict == "NEEDS_IMPROVEMENT"
    assert result.weakest_dimension == "specificity"


async def test_evaluate_disabled_returns_pass():
    deps = make_test_deps()
    deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})
    result = await evaluate_node_output(
        output_json='{"anything": true}',
        rubric=SAMPLE_RUBRIC,
        deps=deps,
    )
    assert result.verdict == "PASS"


# --- run_with_evaluation tests ---

import pydantic_core
from pydantic_ai.models.test import _JsonSchemaTestData

from academic_pipeline.models.research import RQBrief
from academic_pipeline.research.agents import agents as _agents


async def test_run_with_evaluation_passes_first_try():
    """Generator output passes evaluation on first try — no revision."""
    deps = make_test_deps()
    deps.config = deps.config.model_copy(
        update={"evaluator_models": ["test"], "enable_node_evaluation": True}
    )

    schema = RQBrief.model_json_schema()
    gen_json = pydantic_core.to_json(_JsonSchemaTestData(schema, 0).generate()).decode()

    agent = _agents["research_question"]
    gen_model = TestModel(custom_output_text=gen_json, call_tools=[])

    with agent.override(model=gen_model), _override_evaluators(PASS_EVAL_JSON, ["test"]):
        result = await run_with_evaluation(
            agent=agent,
            context="Topic: AI in education",
            rubric=SAMPLE_RUBRIC,
            deps=deps,
        )

    assert result.output is not None


async def test_run_with_evaluation_caps_iterations():
    """Evaluator always says NEEDS_IMPROVEMENT — caps at max_node_iterations."""
    deps = make_test_deps()
    deps.config = deps.config.model_copy(
        update={
            "evaluator_models": ["test"],
            "enable_node_evaluation": True,
            "max_node_iterations": 2,
        }
    )

    schema = RQBrief.model_json_schema()
    gen_json = pydantic_core.to_json(_JsonSchemaTestData(schema, 0).generate()).decode()

    agent = _agents["research_question"]
    gen_model = TestModel(custom_output_text=gen_json, call_tools=[])

    with agent.override(model=gen_model), _override_evaluators(FAIL_EVAL_JSON, ["test"]):
        result = await run_with_evaluation(
            agent=agent,
            context="Topic: AI in education",
            rubric=SAMPLE_RUBRIC,
            deps=deps,
        )

    assert result.output is not None


async def test_run_with_evaluation_skips_when_disabled():
    """When enable_node_evaluation=False, runs agent once without evaluation."""
    deps = make_test_deps()
    deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

    schema = RQBrief.model_json_schema()
    gen_json = pydantic_core.to_json(_JsonSchemaTestData(schema, 0).generate()).decode()

    agent = _agents["research_question"]
    gen_model = TestModel(custom_output_text=gen_json, call_tools=[])

    with agent.override(model=gen_model):
        result = await run_with_evaluation(
            agent=agent,
            context="Topic: AI in education",
            rubric=SAMPLE_RUBRIC,
            deps=deps,
        )

    assert result.output is not None
