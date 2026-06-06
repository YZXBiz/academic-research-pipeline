"""Tests for research agent YAML specs."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai_skills import SkillsCapability

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.research.agents import agents
from academic_pipeline.runtime.model_registry import build_agent


AGENTS_DIR = Path("src/academic_pipeline/research/specs")
EXPECTED_SPECS = [
    "research_question.yaml",
    "research_architect.yaml",
    "bibliography.yaml",
    "source_verification.yaml",
    "synthesis.yaml",
    "report_compiler.yaml",
    "editor_in_chief.yaml",
    # PRD §6.1.T6 — ethics_review.yaml moved to integrity/specs/.
    "risk_of_bias.yaml",
    "meta_analysis.yaml",
    "monitoring.yaml",
]


class TestResearchAgentSpecs:
    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_exists(self, spec_name: str) -> None:
        assert (AGENTS_DIR / spec_name).exists()

    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_loads(self, spec_name: str) -> None:
        agent = build_agent(spec_name.removesuffix(".yaml"), AGENTS_DIR / spec_name, deps_type=PipelineDeps)
        assert agent is not None


class TestBibliographyToolWiring:
    def test_bibliography_has_exa_tools(self) -> None:
        agent = agents["bibliography"]
        toolset = agent._function_toolset  # pyright: ignore[reportAttributeAccessIssue]
        tool_names = set(toolset.tools.keys()) if isinstance(toolset.tools, dict) else {t.name for t in toolset.tools}
        assert "web_search_exa" in tool_names
        assert "web_fetch_exa" in tool_names

    def test_bibliography_has_skills_capability(self) -> None:
        agent = agents["bibliography"]
        caps = agent._root_capability.capabilities  # pyright: ignore[reportAttributeAccessIssue]
        skills_caps = [c for c in caps if isinstance(c, SkillsCapability)]
        assert len(skills_caps) == 1
