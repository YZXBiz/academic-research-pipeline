"""Integration tests for the PydanticAI integrity subgraph."""

from __future__ import annotations

import pytest
from pydantic_graph.persistence.in_mem import SimpleStatePersistence

from academic_pipeline.integrity.agents import agents as _integrity_agents
from academic_pipeline.integrity.graph import (
    IntegrityCheckNode,
    build_integrity_graph,
)
from academic_pipeline.integrity.state import IntegrityState
from academic_pipeline.models.integrity import (
    ComplianceReport,
    IntegrityVerificationOutput,
)
from tests.conftest import make_structured_test_model, make_structured_test_model_with_overrides, make_test_deps


pytestmark = pytest.mark.anyio


def _override_integrity_agents(
    integrity_model: object | None = None,
) -> tuple[object, object]:
    """Return (integrity_model, compliance_model) for overriding both integrity agents."""
    if integrity_model is None:
        integrity_model = make_structured_test_model(IntegrityVerificationOutput)
    compliance_model = make_structured_test_model(ComplianceReport)
    return integrity_model, compliance_model


class TestIntegrityGraph:
    async def test_graph_runs_to_completion(self) -> None:
        graph = build_integrity_graph()
        state = IntegrityState(paper_draft={"title": "Test", "content": "A paper about machine learning."})
        deps = make_test_deps()
        iv_model, cc_model = _override_integrity_agents()

        with _integrity_agents["integrity_verification"].override(model=iv_model), \
             _integrity_agents["compliance_check"].override(model=cc_model):
            result = await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert result.output is not None
        assert state.integrity_report != {}

    async def test_graph_with_persistence(self) -> None:
        graph = build_integrity_graph()
        state = IntegrityState(paper_draft={"title": "Test", "content": "Test paper."})
        deps = make_test_deps()
        persistence = SimpleStatePersistence()
        iv_model, cc_model = _override_integrity_agents()

        with _integrity_agents["integrity_verification"].override(model=iv_model), \
             _integrity_agents["compliance_check"].override(model=cc_model):
            result = await graph.run(
                IntegrityCheckNode(),
                state=state,
                deps=deps,
                persistence=persistence,
            )

        assert result.output is not None

    async def test_graph_fail_verdict(self) -> None:
        graph = build_integrity_graph()
        state = IntegrityState(paper_draft={"title": "Test", "content": "Plagiarized content here."})
        deps = make_test_deps()
        iv_model = make_structured_test_model_with_overrides(
            IntegrityVerificationOutput,
            {"verdict": "FAIL", "summary": "Plagiarism detected.", "report": "Details."},
        )
        cc_model = make_structured_test_model(ComplianceReport)

        with _integrity_agents["integrity_verification"].override(model=iv_model), \
             _integrity_agents["compliance_check"].override(model=cc_model):
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert "FAIL" in str(state.integrity_report.get("verdict"))

    async def test_graph_pre_and_final_phases(self) -> None:
        graph = build_integrity_graph()
        deps = make_test_deps()
        iv_model, cc_model = _override_integrity_agents()

        for phase in ("pre", "final"):
            state = IntegrityState(paper_draft={"title": "Test", "content": "Paper."}, integrity_phase=phase)
            with _integrity_agents["integrity_verification"].override(model=iv_model), \
                 _integrity_agents["compliance_check"].override(model=cc_model):
                await graph.run(IntegrityCheckNode(), state=state, deps=deps)
            assert state.integrity_report != {}
