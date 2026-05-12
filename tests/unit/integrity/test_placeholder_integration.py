"""Integration test for placeholder scan inside IntegrityCheckNode."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from academic_pipeline.integrity.placeholder_scan import scan_placeholders


if TYPE_CHECKING:
    from pathlib import Path


def test_blocking_placeholder_in_paper_draft_is_caught() -> None:
    """A paper containing CRD42024-XXXXXX gets a BLOCKING finding."""
    paper = """
    # Methods
    Protocol registered (CRD42024-XXXXXX) prior to screening.
    Pooled estimate: 0.014.
    """
    findings = scan_placeholders(paper)
    blocking = [f for f in findings if f.severity == "BLOCKING"]
    assert len(blocking) >= 1, f"Expected blocking finding, got {findings}"
    assert any(f.label == "PROSPERO placeholder" for f in blocking)


def test_pending_only_paper_no_blocking() -> None:
    """[PENDING:...] is OK in pre-integrity but FAIL at final."""
    paper = "Pooled ΔAUROC: [PENDING: from full meta-analysis]."
    findings = scan_placeholders(paper)
    blocking = [f for f in findings if f.severity == "BLOCKING"]
    pending = [f for f in findings if f.severity == "PENDING"]
    assert blocking == []
    assert len(pending) == 1


def test_clean_paper_no_findings() -> None:
    paper = "Pooled ΔAUROC = 0.014 (95% CI: 0.004 to 0.024) [smith2024]."
    findings = scan_placeholders(paper)
    assert findings == []


@pytest.mark.asyncio
async def test_integrity_check_node_bumps_verdict_on_blocking_placeholder(tmp_path: Path) -> None:
    """When the LLM verifier returns PASS but the scanner finds a BLOCKING
    placeholder, IntegrityCheckNode must bump the verdict to FAIL."""
    from academic_pipeline.integrity.graph import IntegrityCheckNode
    from academic_pipeline.integrity.state import IntegrityState
    from academic_pipeline.models.integrity import IntegrityVerificationOutput
    from tests.conftest import make_test_deps

    state = IntegrityState(
        paper_draft="Protocol registered (CRD42024-XXXXXX).",  # type: ignore[arg-type]
        integrity_phase="pre",
        compliance_stage="2.5",
    )
    deps = make_test_deps()
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    fake_output = IntegrityVerificationOutput(
        verdict="PASS", report="ok", summary="ok", failure_modes=[],
    )
    fake_result = MagicMock()
    fake_result.output = fake_output

    with patch(
        "academic_pipeline.integrity.graph.traced_agent_run",
        new=AsyncMock(return_value=fake_result),
    ):
        node = IntegrityCheckNode()
        await node.run(ctx)

    assert "FAIL" in str(ctx.state.integrity_report["verdict"])
    assert "CRD42024-XXXXXX" in ctx.state.integrity_report["raw"]


@pytest.mark.asyncio
async def test_integrity_check_node_pending_only_pre_passes(tmp_path: Path) -> None:
    """In pre-integrity phase, [PENDING:...] markers do NOT bump verdict to FAIL."""
    from academic_pipeline.integrity.graph import IntegrityCheckNode
    from academic_pipeline.integrity.state import IntegrityState
    from academic_pipeline.models.integrity import IntegrityVerificationOutput
    from tests.conftest import make_test_deps

    state = IntegrityState(
        paper_draft="ΔAUROC: [PENDING: from full meta-analysis]",  # type: ignore[arg-type]
        integrity_phase="pre",
        compliance_stage="2.5",
    )
    deps = make_test_deps()
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    fake_output = IntegrityVerificationOutput(
        verdict="PASS", report="ok", summary="ok", failure_modes=[],
    )
    fake_result = MagicMock()
    fake_result.output = fake_output

    with patch(
        "academic_pipeline.integrity.graph.traced_agent_run",
        new=AsyncMock(return_value=fake_result),
    ):
        node = IntegrityCheckNode()
        await node.run(ctx)

    assert "PASS" in str(ctx.state.integrity_report["verdict"])


@pytest.mark.asyncio
async def test_integrity_check_node_pending_only_final_fails(tmp_path: Path) -> None:
    """In final-integrity phase, [PENDING:...] markers bump verdict to FAIL."""
    from academic_pipeline.integrity.graph import IntegrityCheckNode
    from academic_pipeline.integrity.state import IntegrityState
    from academic_pipeline.models.integrity import IntegrityVerificationOutput
    from tests.conftest import make_test_deps

    state = IntegrityState(
        paper_draft="ΔAUROC: [PENDING: from full meta-analysis]",  # type: ignore[arg-type]
        integrity_phase="final",
        compliance_stage="4.5",
    )
    deps = make_test_deps()
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    fake_output = IntegrityVerificationOutput(
        verdict="PASS", report="ok", summary="ok", failure_modes=[],
    )
    fake_result = MagicMock()
    fake_result.output = fake_output

    with patch(
        "academic_pipeline.integrity.graph.traced_agent_run",
        new=AsyncMock(return_value=fake_result),
    ):
        node = IntegrityCheckNode()
        await node.run(ctx)

    assert "FAIL" in str(ctx.state.integrity_report["verdict"])
