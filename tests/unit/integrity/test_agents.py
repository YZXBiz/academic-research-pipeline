"""Tests for integrity verification agent via PydanticAI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic_ai.models.test import TestModel

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.models.integrity import IntegrityVerificationOutput
from academic_pipeline.runtime.model_registry import build_agent
from academic_pipeline.tools.integrity_tools import (
    check_plagiarism_heuristic,
    detect_ai_style_indicators,
    extract_claims,
)
from tests.conftest import make_test_deps


if TYPE_CHECKING:
    from pydantic_ai import Agent


pytestmark = pytest.mark.anyio

SPEC_PATH = Path("src/academic_pipeline/integrity/specs/integrity_verification.yaml")


def _load_agent() -> Agent[PipelineDeps, IntegrityVerificationOutput]:
    """Load the integrity verification agent from YAML spec."""
    return build_agent(
        "integrity_verification",
        SPEC_PATH,
        deps_type=PipelineDeps,
        output_type=IntegrityVerificationOutput,
        tools=[extract_claims, check_plagiarism_heuristic, detect_ai_style_indicators],
    )


class TestIntegrityAgent:
    """Tests for integrity verification agent YAML spec."""

    def test_spec_file_exists(self) -> None:
        """Agent spec YAML file must exist on disk."""
        assert SPEC_PATH.exists(), f"Agent spec not found: {SPEC_PATH}"

    def test_agent_loads_from_spec(self) -> None:
        """Agent.from_file parses the YAML without errors."""
        agent = _load_agent()
        assert agent is not None
        assert agent.name == "integrity_verification_agent"

    async def test_agent_runs_with_test_model(self) -> None:
        """Agent produces structured output when driven by TestModel."""
        agent = _load_agent()
        model = TestModel(call_tools=[])
        deps = make_test_deps()
        with agent.override(model=model):
            result = await agent.run(
                "Check this paper for integrity: AI improves outcomes.",
                deps=deps,
            )
            assert isinstance(result.output, IntegrityVerificationOutput)
            assert result.output.verdict is not None

    async def test_agent_tools_are_registered(self) -> None:
        """All three integrity tools are available to the agent."""
        agent = _load_agent()
        tool_names = set(agent._function_toolset.tools.keys())
        assert "extract_claims" in tool_names
        assert "check_plagiarism_heuristic" in tool_names
        assert "detect_ai_style_indicators" in tool_names

    async def test_agent_fail_verdict(self) -> None:
        """Agent output containing FAIL verdict is correctly returned."""
        agent = _load_agent()
        model = TestModel(
            custom_output_args={"verdict": "FAIL", "summary": "2 SERIOUS issues.", "report": "Correction list."},
            call_tools=[],
        )
        deps = make_test_deps()
        with agent.override(model=model):
            result = await agent.run(
                "Check this paper for integrity.",
                deps=deps,
            )
            assert result.output.verdict == "FAIL"
