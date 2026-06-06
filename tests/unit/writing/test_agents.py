"""Tests for writing agent YAML specs."""

from __future__ import annotations

from pathlib import Path

import pytest

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.runtime.model_registry import build_agent


AGENTS_DIR = Path("src/academic_pipeline/writing/specs")
EXPECTED_SPECS = [
    "intake.yaml",
    "literature_strategist.yaml",
    "structure_architect.yaml",
    "argument_builder.yaml",
    "draft_writer.yaml",
    "citation_compliance.yaml",
    "abstract.yaml",
    "peer_reviewer.yaml",
    "formatter.yaml",
    "visualization.yaml",
    "revision_coach.yaml",
]


class TestWritingAgentSpecs:
    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_exists(self, spec_name: str) -> None:
        assert (AGENTS_DIR / spec_name).exists()

    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_loads(self, spec_name: str) -> None:
        agent = build_agent(spec_name.removesuffix(".yaml"), AGENTS_DIR / spec_name, deps_type=PipelineDeps)
        assert agent is not None
