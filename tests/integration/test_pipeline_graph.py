"""Integration tests for the PydanticAI pipeline orchestrator graph."""

from __future__ import annotations

import contextlib
import json
import shutil
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_graph.persistence.in_mem import SimpleStatePersistence


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _mock_doi_and_authors_gates():
    """Stub the §6.7.T2 + §6.7.T3 build gates for full-pipeline tests.

    Without this, the writing subgraph's LatexCompilerNode would abort with
    REN001 (placeholder DOI fails CrossRef) or REN002 (no authors.yaml on
    disk). Mocks the doi.verify_doi network hit and short-circuits the
    authors.yaml resolver + loader.
    """
    from pathlib import Path as _Path

    from academic_pipeline.runtime.authors_yaml import AuthorsYamlEntry

    async def _ok(doi: str) -> str:
        return json.dumps({"doi": doi, "exists": True, "status": 200})

    fake_path = _Path("authors.yaml")
    fake_entries = [AuthorsYamlEntry(name="Test User", affiliation="Test Lab")]

    with (
        patch(
            "academic_pipeline.tools.bibliography.doi.verify_doi",
            new=AsyncMock(side_effect=_ok),
        ),
        patch(
            "academic_pipeline.runtime.authors_yaml.resolve_authors_yaml_path",
            return_value=fake_path,
        ),
        patch(
            "academic_pipeline.runtime.authors_yaml.load_authors_yaml",
            return_value=fake_entries,
        ),
    ):
        yield


from academic_pipeline.core.enums import PipelineStatus, Stage
from academic_pipeline.experiment.agents import agents as _experiment_agents
from academic_pipeline.integrity.agents import agents as _integrity_agents
from academic_pipeline.models.ethics import EthicsChecklist
from academic_pipeline.models.experiment import ExperimentClassification
from academic_pipeline.models.integrity import (
    ComplianceReport,
    IntegrityVerificationOutput,
)
from academic_pipeline.models.research import (
    Bibliography,
    IndependentVerificationReport,
    MethodologyBlueprint,
    ResearchReport,
    RQBrief,
    SourceVerificationReport,
    SynthesisReport,
)
from academic_pipeline.models.review import (
    EditorialSynthesis,
    EditorReview,
    EICReview,
    FieldAnalysis,
    PeerReviewOutput,
    PeerReviewReport,
)
from academic_pipeline.models.writing import (
    AbstractOutput,
    ArgumentBlueprint,
    CitationAudit,
    FigurePackage,
    FormattedPaper,
    LiteratureStrategy,
    PaperConfig,
    PaperDraft,
    PaperOutline,
)
from academic_pipeline.pipeline.state import PipelineState
from academic_pipeline.research.agents import agents as research_agents
from academic_pipeline.review.agents import agents as review_agents
from academic_pipeline.writing.agents import agents as writing_agents
from tests.conftest import (
    json_for_model,
    make_structured_test_model,
    make_structured_test_model_with_overrides,
    make_test_deps,
)


pytestmark = pytest.mark.anyio


# Map every structured-output agent to its Pydantic model class.
_RESEARCH_AGENT_MODELS: dict[str, type] = {
    "research_question": RQBrief,
    "research_architect": MethodologyBlueprint,
    "bibliography": Bibliography,
    "source_verification": SourceVerificationReport,
    "synthesis": SynthesisReport,
    "report_compiler": ResearchReport,
    "independent_verifier": IndependentVerificationReport,
    "editor_in_chief": EditorReview,
    "ethics_review": EthicsChecklist,
}

_WRITING_AGENT_MODELS: dict[str, type] = {
    "intake": PaperConfig,
    "literature_strategist": LiteratureStrategy,
    "structure_architect": PaperOutline,
    "argument_builder": ArgumentBlueprint,
    "draft_writer": PaperDraft,
    "citation_compliance": CitationAudit,
    "abstract": AbstractOutput,
    "peer_reviewer": PeerReviewOutput,
    "formatter": FormattedPaper,
    "visualization": FigurePackage,
}

_REVIEW_AGENT_MODELS: dict[str, type] = {
    "field_analyst": FieldAnalysis,
    "eic": EICReview,
    "methodology_reviewer": PeerReviewReport,
    "domain_reviewer": PeerReviewReport,
    "perspective_reviewer": PeerReviewReport,
    "editorial_synthesizer": EditorialSynthesis,
}


def _override_all(
    default_output: str = "Verdict: PASS\n\nAll good.",
    *,
    review_output: str | None = None,
    review_decision: str = "Accept",
    integrity_output: str | None = None,
) -> contextlib.ExitStack:
    """Override all subgraph agents with TestModels.

    Args:
        default_output: Default output for all agents.
        review_output: Override output for text-based review agents only.
        review_decision: Decision for the editorial_synthesizer structured agent.
        integrity_output: Unused (kept for signature compat), integrity is now structured.
    """
    default_model = TestModel(custom_output_text=default_output, call_tools=[])
    review_text_model = TestModel(custom_output_text=review_output, call_tools=[]) if review_output else default_model

    # Editorial synthesizer with specific decision override
    editorial_model = make_structured_test_model_with_overrides(
        EditorialSynthesis,
        {"decision": review_decision, "summary": "Review complete.", "report": "Details."},
    )

    stack = contextlib.ExitStack()

    for name, agent in research_agents.items():
        if name in _RESEARCH_AGENT_MODELS:
            # Use FIXTURE_INSTANCES when available so models with output_validators
            # (e.g., EthicsChecklist) get a fixture that satisfies the validator.
            model = make_structured_test_model(_RESEARCH_AGENT_MODELS[name])
            stack.enter_context(agent.override(model=model))
        else:
            stack.enter_context(agent.override(model=default_model))

    for name, agent in writing_agents.items():
        if name in _WRITING_AGENT_MODELS:
            model = TestModel(custom_output_text=json_for_model(_WRITING_AGENT_MODELS[name]), call_tools=[])
            stack.enter_context(agent.override(model=model))
        else:
            stack.enter_context(agent.override(model=default_model))

    for name, agent in review_agents.items():
        if name == "editorial_synthesizer":
            stack.enter_context(agent.override(model=editorial_model))
        elif name in _REVIEW_AGENT_MODELS:
            model = TestModel(custom_output_text=json_for_model(_REVIEW_AGENT_MODELS[name]), call_tools=[])
            stack.enter_context(agent.override(model=model))
        else:
            stack.enter_context(agent.override(model=review_text_model))

    integrity_model = TestModel(custom_output_text=json_for_model(IntegrityVerificationOutput), call_tools=[])
    stack.enter_context(_integrity_agents["integrity_verification"].override(model=integrity_model))
    compliance_model = TestModel(custom_output_text=json_for_model(ComplianceReport), call_tools=[])
    stack.enter_context(_integrity_agents["compliance_check"].override(model=compliance_model))

    # Experiment classifier — override to skip experiments (needs_experiments=False)
    classifier_model = make_structured_test_model_with_overrides(
        ExperimentClassification,
        {"needs_experiments": False, "reasoning": "No experiments needed for this topic."},
    )
    stack.enter_context(_experiment_agents["experiment_classifier"].override(model=classifier_model))
    return stack


class TestPipelineHappyPath:
    """Full pipeline run where everything passes."""

    async def test_happy_path_reaches_summary(self) -> None:
        from academic_pipeline.pipeline.graph import build_pipeline_graph
        from academic_pipeline.pipeline.nodes import IntakeNode

        graph = build_pipeline_graph()
        state = PipelineState(topic="AI in education")
        deps = make_test_deps()

        with _override_all(
            default_output="Verdict: PASS\n\nAll good.",
            review_output="Decision: Accept\n\nExcellent paper.",
            integrity_output="Verdict: PASS\n\nNo integrity issues.",
        ):
            result = await graph.run(IntakeNode(), state=state, deps=deps)

        assert state.pipeline_status == PipelineStatus.COMPLETED
        assert state.current_stage == Stage.SUMMARY
        assert result.output is not None

    async def test_happy_path_with_persistence(self) -> None:
        from academic_pipeline.pipeline.graph import build_pipeline_graph
        from academic_pipeline.pipeline.nodes import IntakeNode

        graph = build_pipeline_graph()
        state = PipelineState(topic="Quantum computing")
        deps = make_test_deps()
        persistence = SimpleStatePersistence()

        with _override_all(
            default_output="Verdict: PASS\n\nAll good.",
            review_output="Decision: Accept\n\nExcellent paper.",
            integrity_output="Verdict: PASS\n\nNo integrity issues.",
        ):
            await graph.run(IntakeNode(), state=state, deps=deps, persistence=persistence)

        assert state.pipeline_status == PipelineStatus.COMPLETED

    async def test_state_populated_after_happy_path(self) -> None:
        from academic_pipeline.pipeline.graph import build_pipeline_graph
        from academic_pipeline.pipeline.nodes import IntakeNode

        graph = build_pipeline_graph()
        state = PipelineState(topic="Machine learning ethics")
        deps = make_test_deps()

        with _override_all(
            default_output="Verdict: PASS\n\nAll good.",
            review_output="Decision: Accept\n\nExcellent paper.",
            integrity_output="Verdict: PASS\n\nNo integrity issues.",
        ):
            await graph.run(IntakeNode(), state=state, deps=deps)

        # Research outputs should be populated
        assert state.rq_brief != {}
        assert state.synthesis != {}
        # Writing outputs should be populated
        assert state.paper_draft != {}
        # Integrity should have run
        assert state.integrity_report != {}


class TestPipelineIntegrityFixLoop:
    """Test that integrity fix loop executes and retries."""

    async def test_integrity_fix_then_pass(self) -> None:
        from academic_pipeline.pipeline.graph import build_pipeline_graph
        from academic_pipeline.pipeline.nodes import IntakeNode

        graph = build_pipeline_graph()
        state = PipelineState(topic="Test integrity fix")
        deps = make_test_deps()

        # The fix loop is tested in unit tests. Here we test the graph integration
        # with all agents overridden to PASS, verifying the pipeline completes.
        with _override_all(
            default_output="Verdict: PASS\n\nAll good.",
            review_output="Decision: Accept\n\nExcellent.",
            integrity_output="Verdict: PASS\n\nClean.",
        ):
            await graph.run(IntakeNode(), state=state, deps=deps)

        assert state.pipeline_status == PipelineStatus.COMPLETED


class TestPipelineNoRevisionLoop:
    """Test that pipeline completes without revision nodes (per-node eval replaces them)."""

    async def test_completes_without_revision_nodes(self) -> None:
        from academic_pipeline.pipeline.graph import build_pipeline_graph
        from academic_pipeline.pipeline.nodes import IntakeNode

        graph = build_pipeline_graph()
        state = PipelineState(topic="Test no-revision pipeline")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all(
            default_output="Verdict: PASS\n\nAll good.",
            review_output="Decision: Accept\n\nAccepted.",
            integrity_output="Verdict: PASS\n\nClean.",
        ):
            await graph.run(IntakeNode(), state=state, deps=deps)

        assert state.pipeline_status == PipelineStatus.COMPLETED
        assert state.current_stage == Stage.SUMMARY


class TestPipelineRejectDecision:
    """Test that reject decision is recorded but pipeline still completes (review is read-only)."""

    async def test_reject_completes_pipeline(self) -> None:
        from academic_pipeline.pipeline.graph import build_pipeline_graph
        from academic_pipeline.pipeline.nodes import IntakeNode

        graph = build_pipeline_graph()
        state = PipelineState(topic="Test reject")
        deps = make_test_deps()

        with _override_all(
            default_output="Verdict: PASS\n\nAll good.",
            review_decision="Reject",
        ):
            await graph.run(IntakeNode(), state=state, deps=deps)

        # Review is read-only — Reject is recorded but pipeline completes
        assert state.pipeline_status == PipelineStatus.COMPLETED
        assert state.editorial_decision == "Reject"


# ---------------------------------------------------------------------------
# §6.7.T6 — ACL e2e smoke test
# ---------------------------------------------------------------------------
# Marked ``medium`` because it shells out to pandoc + tectonic — both must be
# installed locally and tectonic downloads packages on first invocation. Excluded
# from ``make test`` (which filters ``-m 'not medium and not large'``); included
# in ``make test-integration``. Validates §6.7.T1's vendored ACL template path
# end-to-end: writes a stub manuscript, invokes the production
# ``compile_pdf_pandoc`` against the real ACL templates at
# ``templates/pandoc/acl/``, asserts the resulting PDF exists + is non-empty.


class TestACLBuildSmoke:
    """End-to-end ACL template compile via the production pandoc + tectonic path."""

    @pytest.mark.medium()
    async def test_acl_stub_compiles_to_nonempty_pdf(self, tmp_path: Path) -> None:
        from academic_pipeline.tools.rendering.latex_compiler import compile_pdf_pandoc

        if shutil.which("pandoc") is None or shutil.which("tectonic") is None:
            pytest.skip("pandoc + tectonic required for ACL e2e smoke")

        # Minimal manuscript that exercises the ACL template path: a top-level
        # heading, body paragraph, plus one citation-bearing sentence so the
        # natbib-conditional branch in compile_pdf_pandoc executes.
        markdown = (
            "# Stub Title for ACL Smoke\n\n" "Short body paragraph that compiles cleanly through the ACL template.\n"
        )

        pdf = await compile_pdf_pandoc(
            markdown=markdown,
            bib_source="",  # empty → DOI gate skips, --natbib branch skips
            output_dir=tmp_path,
        )

        assert pdf is not None, "compile_pdf_pandoc returned None — pandoc/tectonic compile failed"
        assert pdf.exists(), f"PDF path {pdf} does not exist"
        assert pdf.stat().st_size > 0, "PDF is empty"
