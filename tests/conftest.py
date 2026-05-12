"""Shared test fixtures for the academic pipeline test suite."""

from __future__ import annotations

import os

import truststore


# Must run before any SSL-using imports to patch the SSL context for Zscaler proxy
truststore.inject_into_ssl()

import pydantic_ai.models


pydantic_ai.models.ALLOW_MODEL_REQUESTS = False

# Set dummy OpenAI API key so Agent.from_file() can instantiate OpenAI-backed
# agents (e.g. figure_verifier, independent_verifier) without erroring at import
# time.  Tests override these agents with TestModel, so the key is never used.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-openai-key")

from typing import Any

import pydantic_core
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel, _JsonSchemaTestData

from academic_pipeline.config import PipelineConfig
from academic_pipeline.core.deps import PipelineDeps


def make_test_model(output: str = "Test output.") -> TestModel:
    """Create a TestModel with custom output text and no tool calls."""
    return TestModel(custom_output_text=output, call_tools=[])


def make_test_deps() -> PipelineDeps:
    """Create PipelineDeps with test-safe defaults."""
    config = PipelineConfig(
        anthropic_api_key="sk-test-fake-key",  # type: ignore[arg-type]
        model_name="test",
        max_budget_tokens=999_999,
        tool_call_delay_seconds=0,
    )
    return PipelineDeps.create(config=config)


def json_for_model(model_cls: type[BaseModel], seed: int = 0) -> str:
    """Generate valid JSON text from a Pydantic model's schema for TestModel.

    PromptedOutput agents need TestModel with custom_output_text containing valid JSON that matches the model's schema.
    """
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, seed).generate()
    return pydantic_core.to_json(data).decode()


def make_structured_test_model(model_cls: type[BaseModel], seed: int = 0) -> TestModel:
    """Create a TestModel that returns valid JSON for a PromptedOutput agent.

    Uses pre-built fixture instances when available to pass field_validators.
    """
    _init_fixture_instances()
    if model_cls in FIXTURE_INSTANCES:
        json_text = FIXTURE_INSTANCES[model_cls].model_dump_json()
    else:
        json_text = json_for_model(model_cls, seed)
    return TestModel(custom_output_text=json_text, call_tools=[])


def make_structured_test_model_with_overrides(
    model_cls: type[BaseModel],
    overrides: dict[str, Any],
    seed: int = 0,
) -> TestModel:
    """Create a TestModel returning JSON with specific field overrides.

    Generates valid JSON from the schema, then patches specific fields. Useful for testing specific verdicts, decisions,
    etc.
    """
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, seed).generate()
    if isinstance(data, dict):
        data.update(overrides)
    json_text = pydantic_core.to_json(data).decode()
    return TestModel(custom_output_text=json_text, call_tools=[])


def make_union_test_model(model_cls: type[BaseModel], *, kind: str | None = None, seed: int = 0) -> TestModel:
    """Create a TestModel for PromptedOutput(A | B) union agents.

    PydanticAI wraps union outputs as {result: {kind: ClassName, data: {...}}}.
    Uses pre-built fixture instances when available to pass field_validators.
    """
    import json

    _init_fixture_instances()
    if model_cls in FIXTURE_INSTANCES:
        data = json.loads(FIXTURE_INSTANCES[model_cls].model_dump_json())
    else:
        schema = model_cls.model_json_schema()
        data = _JsonSchemaTestData(schema, seed).generate()
    wrapped = {"result": {"kind": kind or model_cls.__name__, "data": data}}
    return TestModel(custom_output_text=json.dumps(wrapped), call_tools=[])


FIXTURE_INSTANCES: dict[type, Any] = {}


def _init_fixture_instances() -> None:
    """Populate FIXTURE_INSTANCES on first call. Lazy to avoid circular imports."""
    if FIXTURE_INSTANCES:
        return
    from academic_pipeline.models.experiment import (
        DatasetSpec,
        ExperimentPlan,
        MethodSpec,
    )
    from academic_pipeline.models.experiment_output import (
        ExperimentComplete,
        JudgeVerdict,
    )

    FIXTURE_INSTANCES[ExperimentPlan] = ExperimentPlan(
        research_question="Test RQ",
        hypothesis="Test hypothesis",
        experiment_type="classification",
        dataset_sources=[DatasetSpec(
            name="test-data", source="huggingface",
            download_instruction="from datasets import load_dataset; ds = load_dataset('test/data')",
            expected_shape="(1000, 10)", target_column="label",
        )],
        baseline_methods=[MethodSpec(
            name="LogisticRegression",
            implementation="sklearn.linear_model.LogisticRegression",
            is_baseline=True,
        )],
        proposed_methods=[MethodSpec(
            name="AutoGluon",
            implementation="autogluon.tabular.TabularPredictor",
            is_baseline=False,
        )],
        evaluation_metrics=["accuracy", "f1"],
        success_criteria="AutoGluon outperforms baseline",
    )
    FIXTURE_INSTANCES[ExperimentComplete] = ExperimentComplete(
        results_summary="Test experiment completed",
        results_json_path="/workspace/results.json",
        figures_dir="/workspace/figures",
        seeds_run=[42, 123, 456],
    )
    FIXTURE_INSTANCES[JudgeVerdict] = JudgeVerdict(
        verdict="APPROVED",
        checklist={"data_loaded": True, "model_trained": True, "metrics_reported": True},
        suggestions=[],
        further_experiments=[],
    )

    # Ethics checklist: must satisfy validate_ethics_checklist (12 items in
    # canonical order, justifications ≥ 20 chars, blocker_items consistent).
    from academic_pipeline.models.ethics import (
        STANDARD_ITEMS,
        ChecklistItem,
        EthicsChecklist,
    )

    FIXTURE_INSTANCES[EthicsChecklist] = EthicsChecklist(
        items=[
            ChecklistItem(
                name=name,
                answer=True,
                justification=f"Test fixture: item {name} is compliant per the manuscript.",
                waiver=None,
            )
            for name in STANDARD_ITEMS
        ],
        overall_verdict="pass",
        blocker_items=[],
    )
