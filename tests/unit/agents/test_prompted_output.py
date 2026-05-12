"""Verify all structured-output agents use PromptedOutput wrapping."""

from __future__ import annotations

import pytest

from academic_pipeline.integrity.agents import agents as integrity_agents
from academic_pipeline.research.agents import agents as research_agents
from academic_pipeline.review.agents import agents as review_agents
from academic_pipeline.writing.agents import agents as writing_agents


ALL_REGISTRIES = [
    ("research", research_agents),
    ("writing", writing_agents),
    ("review", review_agents),
    ("integrity", integrity_agents),
]

TEXT_ONLY_AGENTS = {
    ("writing", "revision_coach"),
}


@pytest.mark.parametrize(
    "registry_name,agent_name",
    [
        (rname, aname)
        for rname, registry in ALL_REGISTRIES
        for aname in registry
        if (rname, aname) not in TEXT_ONLY_AGENTS
    ],
)
def test_structured_agent_uses_prompted_output(registry_name: str, agent_name: str) -> None:
    """Every structured agent must use PromptedOutput to avoid Thinking + NativeOutput breakage."""
    from pydantic_ai._output import PromptedOutputSchema

    registries = dict(ALL_REGISTRIES)
    agent = registries[registry_name][agent_name]
    assert isinstance(
        agent._output_schema, PromptedOutputSchema
    ), f"{registry_name}/{agent_name} does not use PromptedOutput — will break with Thinking enabled"
