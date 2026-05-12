"""PydanticAI integrity graph nodes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.core.enums import Verdict
from academic_pipeline.integrity.agents import agents as _agents
from academic_pipeline.integrity.state import IntegrityState
from academic_pipeline.runtime.trace_logger import traced_agent_run
from academic_pipeline.runtime.validators import validate_state


if TYPE_CHECKING:
    from academic_pipeline.models.integrity import ComplianceReport


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PRISMA-trAIce checklists
# ---------------------------------------------------------------------------

_PRISMA_CHECKLIST_25 = """\
Evaluate the paper's METHODS section against these PRISMA-trAIce mandatory items:

- M1 Protocol registration (mandatory): State if AI use was pre-specified in a protocol. Document deviations.
- M2 Tool identification (mandatory): Specify name, version, developer for each AI tool. Include access URL/DOI.
- M3 Purpose and stage (mandatory): Describe the specific SLR stage and task each AI performed.
- M4 Input data (mandatory): Describe data provided to the AI (or state "no fine-tuning performed").
- M5 Output data (mandatory): Describe data produced by the AI and how it was used.
- M6 Human oversight (mandatory): Describe human verification process for AI outputs.
- M7 Prompt engineering (mandatory): Report prompt strategies used (zero-shot, few-shot, chain-of-thought).
- M8 Validation (mandatory): Describe how AI outputs were validated (inter-rater agreement, spot checks).
- M9 Customization (mandatory): Report any fine-tuning, RAG, or custom configuration.
- M10 Error handling (mandatory): Describe how errors, hallucinations, or failures were handled.

Score each item. PASS if evidence found in the paper. FAIL if missing. NOT_APPLICABLE if the item does not apply.
block_decision = "block" if any mandatory item FAILs."""

_PRISMA_CHECKLIST_45 = """\
Evaluate the FULL PAPER against these PRISMA-trAIce reporting items:

- T1 Title (optional): Indicate AI use in the title if it played a substantial role.
- A1 Abstract (optional): Summarize AI tools used and review stages where applied.
- I1 Introduction (recommended): State rationale for using AI tools for specific tasks.
- R1 Reproducibility (highly_recommended): Provide sufficient detail to reproduce AI-assisted steps.
- R2 Code/data availability (highly_recommended): Share code, prompts, or configurations used.
- D1 Limitations (recommended): Discuss limitations of AI tool use.
- D2 Implications (recommended): Discuss implications for future AI use in systematic reviews.

Score each item. PASS if evidence found. FAIL if missing. NOT_APPLICABLE if not relevant.
block_decision = "warn" if any highly_recommended item FAILs. Otherwise "pass"."""

_FIX_INSTRUCTIONS: dict[str, str] = {
    "M1": (
        "Add to Methods: 'The use of AI was [pre-specified in the protocol / "
        "added during the review]. [Describe any deviations.]'"
    ),
    "M2": "Add to Methods: For each AI tool, state its name, version, developer, and access URL or DOI.",
    "M3": "Add to Methods: For each AI tool, describe the specific SLR stage and the precise task it performed.",
    "M4": "Add to Methods: Describe the data provided to each AI tool, or state 'No fine-tuning was performed.'",
    "M5": "Add to Methods: Describe the data produced by each AI tool and how it was integrated.",
    "M6": "Add to Methods: Describe the human verification process for all AI-generated outputs.",
    "M7": "Add to Methods: Report prompt strategies used (e.g., zero-shot, few-shot, chain-of-thought).",
    "M8": "Add to Methods: Describe validation procedures for AI outputs.",
    "M9": "Add to Methods: Report any fine-tuning, RAG, or custom config, or state 'Default configuration was used.'",
    "M10": "Add to Methods: Describe how errors, hallucinations, or AI failures were handled.",
    "T1": "Add 'AI-assisted' or equivalent to the paper title.",
    "A1": "Add to Abstract: Name the AI tools used and which review stages they were applied to.",
    "I1": "Add to Introduction: A rationale for why AI tools were chosen for specific tasks.",
    "R1": "Add to Methods/Appendix: Sufficient detail to reproduce each AI-assisted step.",
    "R2": "Add to Data Availability: Share code, prompts, configurations, or link to a repository.",
    "D1": "Add to Discussion: Limitations of the AI tools used in this review.",
    "D2": "Add to Discussion: Implications for future use of AI in systematic reviews.",
}


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


@dataclass
class ComplianceCheckNode(BaseNode[IntegrityState, PipelineDeps, str]):
    """Check PRISMA-trAIce compliance at the current integrity gate."""

    async def run(self, ctx: GraphRunContext[IntegrityState, PipelineDeps]) -> End[str]:
        """Evaluate paper against stage-specific PRISMA-trAIce checklist."""
        if not ctx.deps.config.enable_compliance_check:
            return End("Compliance check disabled.")

        checklist = _PRISMA_CHECKLIST_25 if ctx.state.compliance_stage == "2.5" else _PRISMA_CHECKLIST_45

        draft = ctx.state.paper_draft
        if isinstance(draft, dict):
            draft_text = json.dumps(draft, indent=2, ensure_ascii=False, default=str)
        else:
            draft_text = str(draft)

        prompt = f"Stage: {ctx.state.compliance_stage}\n\nChecklist:\n{checklist}\n\nPaper:\n{draft_text[:50000]}"

        result = await traced_agent_run(
            _agents["compliance_check"], prompt, deps=ctx.deps, name="compliance_check", phase="03-integrity"
        )
        report: ComplianceReport = result.output

        ctx.state.compliance_report = report
        ctx.state.messages.append({"role": "assistant", "content": report.summary})

        if report.block_decision == "block":
            failed = [item for item in report.items if item.verdict == "fail" and item.tier == "mandatory"]
            fixes = [
                _FIX_INSTRUCTIONS.get(item.item_id, f"Address {item.item_id}: {item.item_name}") for item in failed
            ]
            block_msg = (
                f"COMPLIANCE BLOCK (Stage {ctx.state.compliance_stage}): "
                f"{len(failed)} mandatory PRISMA-trAIce items failed.\n\n"
            )
            block_msg += "\n".join(f"- [{item.item_id}] {item.item_name}: {item.reason}" for item in failed)
            block_msg += "\n\nFix instructions:\n" + "\n".join(f"- {fix}" for fix in fixes)
            logger.warning(block_msg)
            return End(block_msg)

        if report.block_decision == "warn":
            logger.info("Compliance WARN (Stage %s): %s", ctx.state.compliance_stage, report.summary)

        return End(report.summary)


@dataclass
class EthicsChecklistNode(BaseNode[IntegrityState, PipelineDeps, str]):
    """Run the 12-item PRISMA-trAIce structured ethics checklist (Spec 8 / PRD §6.5.T1).

    Replaces the legacy freeform research-side EthicsReviewNode (deletion of
    that node is §6.1.T6, paired with this task). When
    `config.ethics_checklist_enabled=False`, this node is a no-op
    pass-through so legacy integrity flow is preserved.

    The agent (`research.agents['ethics_review']`) is shared with the
    legacy path; ownership migrates to integrity at full cutover.
    """

    async def run(self, ctx: GraphRunContext[IntegrityState, PipelineDeps]) -> IntegrityCheckNode:
        """Score the 12 PRISMA-trAIce items; populate state.ethics_checklist."""
        if not ctx.deps.config.ethics_checklist_enabled:
            return IntegrityCheckNode()

        draft = ctx.state.paper_draft
        if isinstance(draft, dict):
            draft_text = json.dumps(draft, indent=2, ensure_ascii=False, default=str)
        else:
            draft_text = str(draft)

        # The agent's output_validator (validate_ethics_checklist) enforces
        # the 12-item / canonical-order / blocker-consistency invariants.
        result = await traced_agent_run(
            _agents["ethics_review"],
            draft_text[:50000],
            deps=ctx.deps,
            name="ethics_review",
            phase="03-integrity",
        )
        checklist = result.output
        ctx.state.ethics_checklist = checklist

        msg_parts = [f"Ethics checklist verdict: {checklist.overall_verdict.upper()}"]
        if checklist.blocker_items:
            msg_parts.append(f"Blockers: {', '.join(checklist.blocker_items)}")
        ctx.state.messages.append({"role": "assistant", "content": " | ".join(msg_parts)})

        return IntegrityCheckNode()


@dataclass
class IntegrityCheckNode(BaseNode[IntegrityState, PipelineDeps, str]):
    """Run integrity verification on the paper draft."""

    async def run(self, ctx: GraphRunContext[IntegrityState, PipelineDeps]) -> ComplianceCheckNode:
        """Verify integrity (placeholder scan + integrity_verification agent)."""
        validate_state(ctx.state, ["paper_draft"], "IntegrityCheckNode")

        draft = ctx.state.paper_draft
        if isinstance(draft, dict):
            draft_text = json.dumps(draft, indent=2, ensure_ascii=False, default=str)
        else:
            draft_text = str(draft)

        # Layer 4: deterministic placeholder scan (runs BEFORE LLM verifier
        # so its findings always surface even if the LLM call fails).
        from academic_pipeline.integrity.placeholder_scan import (
            format_findings_report,
            scan_placeholders,
        )

        placeholder_findings = scan_placeholders(draft_text)
        blocking = [f for f in placeholder_findings if f.severity == "BLOCKING"]
        pending = [f for f in placeholder_findings if f.severity == "PENDING"]
        scan_report = format_findings_report(placeholder_findings)

        user_prompt = (
            f"Verify the integrity of this paper.\n\n"
            f"Phase: {ctx.state.integrity_phase or 'pre'}\n\n"
            f"Paper:\n{draft_text[:50000]}"
        )

        result = await traced_agent_run(
            _agents["integrity_verification"],
            user_prompt,
            deps=ctx.deps,
            name="integrity_verification",
            phase="03-integrity",
        )
        output = result.output

        # Map structured verdict
        verdict_str = output.verdict.upper()
        # Handle "PASS WITH NOTES" -> PASS
        if verdict_str.startswith("PASS"):
            verdict = Verdict.PASS
        elif verdict_str == "FAIL":
            verdict = Verdict.FAIL
        else:
            verdict = Verdict.FAIL

        # Override verdict if any failure mode is FLAGGED at SERIOUS+ severity
        has_serious_flag = any(
            fm.verdict == "FLAGGED" and fm.severity in ("CRITICAL", "MAJOR") for fm in output.failure_modes
        )
        if has_serious_flag:
            verdict = Verdict.FAIL
            logger.warning("Failure mode check forced verdict to FAIL")

        # Compose with placeholder scan: BLOCKING always FAILs;
        # PENDING only FAILs at the final-integrity phase.
        is_final_phase = ctx.state.integrity_phase == "final"
        if blocking:
            verdict = Verdict.FAIL
            logger.warning(
                "Placeholder scan: %d BLOCKING placeholder(s) — verdict forced to FAIL",
                len(blocking),
            )
        elif pending and is_final_phase:
            verdict = Verdict.FAIL
            logger.warning(
                "Placeholder scan: %d PENDING marker(s) at final integrity — verdict forced to FAIL",
                len(pending),
            )

        report_text = output.report or output.summary
        # Append scan results so they appear in the integrity report artifact.
        report_text = f"{report_text}\n\n{scan_report}"

        ctx.state.integrity_report = {
            "raw": report_text,
            "verdict": str(verdict),
            "failure_modes": [
                {"mode_id": fm.mode_id, "name": fm.name, "verdict": fm.verdict} for fm in output.failure_modes
            ],
            "placeholder_findings": [
                {
                    "label": f.label,
                    "match": f.match,
                    "line": f.line,
                    "severity": f.severity,
                }
                for f in placeholder_findings
            ],
        }
        ctx.state.messages.append({"role": "assistant", "content": report_text})

        return ComplianceCheckNode()


def build_integrity_graph() -> Graph:
    """Build the integrity verification subgraph.

    PRD §6.5.T1: EthicsChecklistNode is the entry node — runs first so the
    structured ethics verdict is in state before integrity verification +
    PRISMA-trAIce compliance check. Skips itself when
    `ethics_checklist_enabled=False`.
    """
    return Graph(  # pyright: ignore[reportReturnType]
        name="integrity",
        nodes=[EthicsChecklistNode, IntegrityCheckNode, ComplianceCheckNode],
    )
