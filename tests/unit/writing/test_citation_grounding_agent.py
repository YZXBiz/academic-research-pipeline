"""Smoke tests for the citation_grounding agent.

These don't exercise the LLM (`ALLOW_MODEL_REQUESTS = False` in conftest).
They just confirm the YAML loads, the agent is registered correctly, and
its `output_type` is bound to `CitationGroundingReport` so a TestModel
override can return a valid grounded report.
"""

from __future__ import annotations

from academic_pipeline.models.citation_grounding import (
    CitationGroundingReport,
    CitationVerdict,
)
from academic_pipeline.writing.agents import agents
from tests.conftest import make_structured_test_model


def test_citation_grounding_agent_is_registered() -> None:
    """The agent must appear in the writing-subgraph registry."""
    assert "citation_grounding" in agents


def test_citation_grounding_agent_runs_with_test_model() -> None:
    """End-to-end with a stub LLM: agent returns a valid CitationGroundingReport."""
    agent = agents["citation_grounding"]
    test_model = make_structured_test_model(CitationGroundingReport)
    with agent.override(model=test_model):
        result = agent.run_sync("Verify citations in: [@s007] supports TAM.")
    # The agent must produce a CitationGroundingReport, not a string or raw dict.
    assert isinstance(result.output, CitationGroundingReport)


def test_citation_verdict_enum_values_are_lowercase() -> None:
    """The agent prompt instructs the model to emit lowercase verdicts —
    keep the enum aligned so JSON parsing succeeds."""
    assert CitationVerdict.SUPPORTS.value == "supports"
    assert CitationVerdict.TANGENTIAL.value == "tangential"
    assert CitationVerdict.CONTRADICTS.value == "contradicts"
    assert CitationVerdict.UNSUPPORTED.value == "unsupported"
