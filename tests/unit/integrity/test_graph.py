"""Tests for PydanticAI integrity graph nodes."""

from __future__ import annotations

import json

import pydantic_core
import pytest
from pydantic_ai.models.test import TestModel, _JsonSchemaTestData
from pydantic_graph import Graph

from academic_pipeline.integrity.agents import agents as _integrity_agents
from academic_pipeline.integrity.graph import ComplianceCheckNode, IntegrityCheckNode
from academic_pipeline.integrity.state import IntegrityState
from academic_pipeline.models.integrity import (
    ComplianceReport,
    IntegrityVerificationOutput,
)
from tests.conftest import make_test_deps


pytestmark = pytest.mark.anyio


def _json_for_model(model_cls: type, seed: int = 0) -> str:
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, seed).generate()
    return pydantic_core.to_json(data).decode()


def _integrity_json(**overrides: object) -> str:
    """Generate valid IntegrityVerificationOutput JSON with optional field overrides."""
    schema = IntegrityVerificationOutput.model_json_schema()
    data = _JsonSchemaTestData(schema, 0).generate()
    data.update(overrides)
    return json.dumps(data)


def _json_for_compliance(**overrides: object) -> str:
    """Generate valid ComplianceReport JSON with optional field overrides."""
    schema = ComplianceReport.model_json_schema()
    data = _JsonSchemaTestData(schema, 0).generate()
    data.update(overrides)
    return json.dumps(data)


class TestIntegrityCheckNode:
    async def test_runs_and_updates_state(self) -> None:
        state = IntegrityState(paper_draft={"title": "Test", "content": "Test paper about AI in education."})
        deps = make_test_deps()
        integrity_model = TestModel(custom_output_text=_json_for_model(IntegrityVerificationOutput), call_tools=[])
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )

        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert state.integrity_report != {}

    async def test_returns_end_with_output(self) -> None:
        state = IntegrityState(paper_draft={"title": "Test", "content": "Test paper."})
        deps = make_test_deps()
        integrity_model = TestModel(custom_output_text=_json_for_model(IntegrityVerificationOutput), call_tools=[])
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="All pass."), call_tools=[]
        )

        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            result = await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert result.output is not None
        assert len(result.output) > 0

    async def test_fail_verdict_captured(self) -> None:
        state = IntegrityState(paper_draft={"title": "Test", "content": "Plagiarized content."})
        deps = make_test_deps()
        integrity_model = TestModel(
            custom_output_text=_integrity_json(verdict="FAIL", summary="Plagiarism found.", report="Details here."),
            call_tools=[],
        )
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )

        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert "FAIL" in str(state.integrity_report.get("verdict"))

    async def test_message_appended(self) -> None:
        state = IntegrityState(paper_draft={"title": "Test", "content": "Test paper."})
        deps = make_test_deps()
        integrity_model = TestModel(custom_output_text=_json_for_model(IntegrityVerificationOutput), call_tools=[])
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )

        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        # IntegrityCheckNode adds 1 message, ComplianceCheckNode adds 1 message
        assert len(state.messages) == 2
        assert state.messages[0]["role"] == "assistant"


class TestCitationGroundingGate:
    """IntegrityCheckNode treats citation-grounding critical mismatches as a hard FAIL.

    Mirrors the deterministic placeholder-scan composition: the
    citation_grounding agent already made the semantic judgement upstream;
    IntegrityCheckNode just enforces it — even when the integrity_verification
    LLM says PASS.
    """

    @staticmethod
    def _grounding_report(*verdicts: str):
        """Build a CitationGroundingReport with one usage per given verdict string."""
        from academic_pipeline.models.citation_grounding import (
            CitationGroundingReport,
            CitationUsage,
            CitationVerdict,
        )

        usages = [
            CitationUsage(
                citation_id=f"s{i:03d}",
                claim_text=f"Claim {i}.",
                section="Introduction",
                verdict=CitationVerdict(v),
                reasoning="test",
                confidence=0.9,
            )
            for i, v in enumerate(verdicts, 1)
        ]
        return CitationGroundingReport(usages=usages, summary="test report")

    async def test_critical_mismatch_forces_fail_over_llm_pass(self) -> None:
        """Agent says PASS, but a CONTRADICTS citation must force the verdict to FAIL."""
        state = IntegrityState(
            paper_draft={"title": "Test", "content": "Test paper."},
            citation_grounding=self._grounding_report("supports", "contradicts"),
        )
        deps = make_test_deps()
        integrity_model = TestModel(
            custom_output_text=_integrity_json(verdict="PASS", summary="Clean.", report="All good."),
            call_tools=[],
        )
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )
        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert "FAIL" in str(state.integrity_report.get("verdict"))

    async def test_all_supports_does_not_force_fail(self) -> None:
        """All-supports grounding must not override an LLM PASS verdict."""
        state = IntegrityState(
            paper_draft={"title": "Test", "content": "Test paper."},
            citation_grounding=self._grounding_report("supports", "tangential", "supports"),
        )
        deps = make_test_deps()
        integrity_model = TestModel(
            custom_output_text=_integrity_json(verdict="PASS", summary="Clean.", report="All good."),
            call_tools=[],
        )
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )
        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert "PASS" in str(state.integrity_report.get("verdict"))

    async def test_none_grounding_is_backward_compatible(self) -> None:
        """A run with no citation_grounding report behaves exactly as before."""
        state = IntegrityState(
            paper_draft={"title": "Test", "content": "Test paper."},
            citation_grounding=None,
        )
        deps = make_test_deps()
        integrity_model = TestModel(
            custom_output_text=_integrity_json(verdict="PASS", summary="Clean.", report="All good."),
            call_tools=[],
        )
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )
        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert "PASS" in str(state.integrity_report.get("verdict"))

    async def test_critical_mismatches_recorded_in_report(self) -> None:
        """The blocking citation usages must surface in the integrity_report artifact."""
        state = IntegrityState(
            paper_draft={"title": "Test", "content": "Test paper."},
            citation_grounding=self._grounding_report("contradicts", "unsupported"),
        )
        deps = make_test_deps()
        integrity_model = TestModel(
            custom_output_text=_integrity_json(verdict="PASS", summary="Clean.", report="All good."),
            call_tools=[],
        )
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )
        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        mismatches = state.integrity_report.get("citation_grounding_mismatches")
        assert mismatches is not None
        assert len(mismatches) == 2


class TestFailureModeWiring:
    async def test_failure_modes_from_structured_output(self) -> None:
        state = IntegrityState(paper_draft={"title": "Test", "content": "Test paper."})
        deps = make_test_deps()
        integrity_model = TestModel(
            custom_output_text=_integrity_json(
                verdict="PASS",
                summary="Clean.",
                report="All good.",
                failure_modes=[
                    {"mode_id": "FM1", "name": "Circular Validation", "verdict": "PASS"},
                    {"mode_id": "FM2", "name": "Phantom Literature", "verdict": "PASS"},
                ],
            ),
            call_tools=[],
        )
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )

        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        fm_list = state.integrity_report.get("failure_modes", [])
        assert len(fm_list) == 2
        assert all(fm["verdict"] == "PASS" for fm in fm_list)

    async def test_flagged_serious_forces_fail(self) -> None:
        state = IntegrityState(paper_draft={"title": "Test", "content": "Test paper."})
        deps = make_test_deps()
        integrity_model = TestModel(
            custom_output_text=_integrity_json(
                verdict="PASS",
                summary="Looks ok.",
                report="Details.",
                failure_modes=[
                    {
                        "mode_id": "FM1",
                        "name": "Circular Validation",
                        "verdict": "FLAGGED",
                        "severity": "CRITICAL",
                        "evidence": "AI-only evidence",
                    },
                ],
            ),
            call_tools=[],
        )
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )

        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        assert state.integrity_report["verdict"] == "FAIL"

    async def test_no_failure_modes_stores_empty(self) -> None:
        state = IntegrityState(paper_draft={"title": "Test", "content": "Test paper."})
        deps = make_test_deps()
        integrity_model = TestModel(custom_output_text=_json_for_model(IntegrityVerificationOutput), call_tools=[])
        compliance_model = TestModel(
            custom_output_text=_json_for_compliance(block_decision="pass", summary="OK."), call_tools=[]
        )

        with (
            _integrity_agents["integrity_verification"].override(model=integrity_model),
            _integrity_agents["compliance_check"].override(model=compliance_model),
        ):
            graph = Graph(nodes=[IntegrityCheckNode, ComplianceCheckNode])
            await graph.run(IntegrityCheckNode(), state=state, deps=deps)

        fm_list = state.integrity_report.get("failure_modes", [])
        assert isinstance(fm_list, list)


class TestComplianceCheckNode:
    async def test_compliance_pass(self) -> None:
        state = IntegrityState(
            paper_draft={"title": "Test", "content": "Methods with AI disclosure..."},
            compliance_stage="2.5",
        )
        deps = make_test_deps()
        compliance_json = _json_for_compliance(block_decision="pass", summary="All items pass.")

        model = TestModel(custom_output_text=compliance_json, call_tools=[])
        with _integrity_agents["compliance_check"].override(model=model):
            graph = Graph(nodes=[ComplianceCheckNode])
            result = await graph.run(ComplianceCheckNode(), state=state, deps=deps)

        assert result.output is not None
        assert state.compliance_report is not None

    async def test_compliance_block(self) -> None:
        state = IntegrityState(
            paper_draft={"title": "Test", "content": "No AI disclosure..."},
            compliance_stage="2.5",
        )
        deps = make_test_deps()
        items = [
            {
                "item_id": "M2",
                "item_name": "Tool identification",
                "tier": "mandatory",
                "verdict": "fail",
                "evidence": "",
                "reason": "No tool identification found.",
            }
        ]
        compliance_json = _json_for_compliance(block_decision="block", summary="M2 fails.", items=items)

        model = TestModel(custom_output_text=compliance_json, call_tools=[])
        with _integrity_agents["compliance_check"].override(model=model):
            graph = Graph(nodes=[ComplianceCheckNode])
            result = await graph.run(ComplianceCheckNode(), state=state, deps=deps)

        assert "COMPLIANCE BLOCK" in result.output
        assert "M2" in result.output

    async def test_compliance_disabled(self) -> None:
        state = IntegrityState(paper_draft={"title": "Test"})
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_compliance_check": False})

        graph = Graph(nodes=[ComplianceCheckNode])
        result = await graph.run(ComplianceCheckNode(), state=state, deps=deps)

        assert result.output == "Compliance check disabled."
        assert state.compliance_report is None

    async def test_compliance_warn(self) -> None:
        state = IntegrityState(
            paper_draft={"title": "Test", "content": "Full paper text..."},
            compliance_stage="4.5",
        )
        deps = make_test_deps()
        compliance_json = _json_for_compliance(block_decision="warn", summary="R1 missing.")

        model = TestModel(custom_output_text=compliance_json, call_tools=[])
        with _integrity_agents["compliance_check"].override(model=model):
            graph = Graph(nodes=[ComplianceCheckNode])
            result = await graph.run(ComplianceCheckNode(), state=state, deps=deps)

        assert result.output is not None
        assert "COMPLIANCE BLOCK" not in result.output
        assert state.compliance_report is not None
        assert state.compliance_report.block_decision == "warn"


# ---------------------------------------------------------------------------
# PRD §6.5.T1 — checklist ethics in integrity subgraph
# ---------------------------------------------------------------------------


class TestEthicsChecklistNode:
    """Spec 8 / PRD §6.5.T1 — EthicsChecklistNode lives in the integrity
    subgraph (replaces the legacy freeform research-side EthicsReviewNode)."""

    async def test_node_class_exists_in_integrity_graph_module(self) -> None:
        """The EthicsChecklistNode class must be importable from
        academic_pipeline.integrity.graph."""
        from academic_pipeline.integrity import graph as ig

        assert hasattr(
            ig, "EthicsChecklistNode"
        ), "academic_pipeline.integrity.graph.EthicsChecklistNode must exist after PRD §6.5.T1"

    async def test_node_skips_when_flag_off(self) -> None:
        """Flag-off path: node is a no-op pass-through (returns successor
        without invoking the agent or touching state.ethics_checklist)."""
        from academic_pipeline.integrity.graph import EthicsChecklistNode

        state = IntegrityState(paper_draft={"title": "T", "content": "x"})
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"ethics_checklist_enabled": False})

        node = EthicsChecklistNode()
        result = await node.run(_StubGraphCtx(state=state, deps=deps))  # type: ignore[arg-type]

        # Returns the next node in the integrity chain; ethics_checklist stays None.
        assert result is not None
        assert state.ethics_checklist is None

    async def test_node_populates_checklist_when_flag_on(self) -> None:
        """Flag-on path: node runs the ethics_review agent and sets
        state.ethics_checklist to the produced EthicsChecklist."""
        from academic_pipeline.integrity.graph import EthicsChecklistNode
        from academic_pipeline.models.ethics import (
            STANDARD_ITEMS,
            ChecklistItem,
            EthicsChecklist,
        )

        items = [
            ChecklistItem(
                name=name,
                answer=True,
                justification=f"Justification text for {name} (>= 20 chars).",
                waiver=None,
            )
            for name in STANDARD_ITEMS
        ]
        canonical = EthicsChecklist(items=items, blocker_items=[], overall_verdict="pass")

        state = IntegrityState(paper_draft={"title": "T", "content": "x"})
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"ethics_checklist_enabled": True})

        # PRD §6.1.T6 — ethics_review agent moved to integrity.agents.
        ethics_model = TestModel(custom_output_text=canonical.model_dump_json(), call_tools=[])
        with _integrity_agents["ethics_review"].override(model=ethics_model):
            node = EthicsChecklistNode()
            await node.run(_StubGraphCtx(state=state, deps=deps))  # type: ignore[arg-type]

        assert state.ethics_checklist is not None
        assert state.ethics_checklist.overall_verdict == "pass"


from dataclasses import dataclass


@dataclass
class _StubGraphCtx:
    """Minimal GraphRunContext substitute for unit-testing single nodes."""

    state: IntegrityState
    deps: object


def test_ethics_checklist_enabled_default_flipped_on() -> None:
    """PRD §6.5.T1 — default-on: chain-of-ideas + thesis-anchored synthesis is
    paired with the new checklist ethics path. The legacy freeform
    EthicsReviewNode in research/graph.py will be removed in §6.1.T6."""
    from academic_pipeline.config import DEFAULT_CONFIG, PipelineConfig

    cfg = PipelineConfig()
    assert cfg.ethics_checklist_enabled is True, "PRD §6.5.T1 flips ethics_checklist_enabled default to True"
    assert DEFAULT_CONFIG.ethics_checklist_enabled is True
