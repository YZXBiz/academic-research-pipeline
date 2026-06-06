"""Tests for review agent YAML specs."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai_skills import SkillsCapability

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.review.agents import agents
from academic_pipeline.runtime.model_registry import build_agent


AGENTS_DIR = Path("src/academic_pipeline/review/specs")
EXPECTED_SPECS = [
    "field_analyst.yaml",
    "eic.yaml",
    "methodology_reviewer.yaml",
    "domain_reviewer.yaml",
    "perspective_reviewer.yaml",
    "editorial_synthesizer.yaml",
]


class TestReviewAgentSpecs:
    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_exists(self, spec_name: str) -> None:
        assert (AGENTS_DIR / spec_name).exists(), f"Missing: {AGENTS_DIR / spec_name}"

    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_loads(self, spec_name: str) -> None:
        agent = build_agent(spec_name.removesuffix(".yaml"), AGENTS_DIR / spec_name, deps_type=PipelineDeps)
        assert agent is not None


class TestReviewerToolWiring:
    @pytest.mark.parametrize("key", ["methodology_reviewer", "domain_reviewer", "perspective_reviewer"])
    def test_reviewer_has_exa_tools(self, key: str) -> None:
        agent = agents[key]
        toolset = agent._function_toolset  # pyright: ignore[reportAttributeAccessIssue]
        tool_names = set(toolset.tools.keys()) if isinstance(toolset.tools, dict) else {t.name for t in toolset.tools}
        assert "web_search_exa" in tool_names
        assert "web_fetch_exa" in tool_names

    @pytest.mark.parametrize("key", ["methodology_reviewer", "domain_reviewer", "perspective_reviewer"])
    def test_reviewer_has_skills_capability(self, key: str) -> None:
        agent = agents[key]
        caps = agent._root_capability.capabilities  # pyright: ignore[reportAttributeAccessIssue]
        skills_caps = [c for c in caps if isinstance(c, SkillsCapability)]
        assert len(skills_caps) == 1
