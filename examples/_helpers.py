"""Shared helpers for example scripts. Private (underscore prefix)."""

from __future__ import annotations

import contextlib
from typing import Any

import pydantic_core
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel, _JsonSchemaTestData


def _output_model(agent: Any) -> type[BaseModel] | None:
    """Extract the inner Pydantic class from an agent's output_type.

    PydanticAI agents in this project use ``PromptedOutput(SomeModel)``.
    PromptedOutput stores the wrapped class as ``.outputs``; we also
    accept a bare BaseModel subclass for direct-output agents and fall
    back to legacy ``.type_`` / ``._type_`` attribute names.
    """
    out = getattr(agent, "output_type", None)
    if out is None:
        return None
    if isinstance(out, type) and issubclass(out, BaseModel):
        return out
    inner = (
        getattr(out, "outputs", None)
        or getattr(out, "type_", None)
        or getattr(out, "_type_", None)
    )
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        return inner
    return None


def _json_for_agent(agent: Any) -> str:
    """Generate valid JSON for a single agent's output schema.

    Mirrors ``tests.conftest.json_for_model`` but operates on the agent
    object rather than a hardcoded model class — examples don't have the
    test fixtures' static agent→model map.
    """
    model_cls = _output_model(agent)
    if model_cls is None:
        return "{}"  # text-output agent — empty string also valid
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, seed=0).generate()
    return pydantic_core.to_json(data).decode()


def override_all_agents() -> contextlib.ExitStack:
    """Override every agent registry's models with TestModel for offline runs.

    Each TestModel returns valid JSON matching its agent's PromptedOutput
    schema, so PromptedOutput validation passes during the mock run.
    """
    from academic_pipeline.research.agents import agents as research_agents
    from academic_pipeline.writing.agents import agents as writing_agents
    from academic_pipeline.review.agents import agents as review_agents
    from academic_pipeline.integrity.agents import agents as integrity_agents
    from academic_pipeline.experiment.agents import agents as experiment_agents

    stack = contextlib.ExitStack()
    for registry in (
        research_agents, writing_agents, review_agents,
        integrity_agents, experiment_agents,
    ):
        for agent in registry.values():
            json_text = _json_for_agent(agent)
            stack.enter_context(agent.override(
                model=TestModel(custom_output_text=json_text, call_tools=[]),
            ))
    return stack
