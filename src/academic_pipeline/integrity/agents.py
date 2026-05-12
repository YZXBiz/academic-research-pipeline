"""Integrity agent registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent, PromptedOutput

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.models.ethics import EthicsChecklist
from academic_pipeline.models.integrity import (
    ComplianceReport,
    IntegrityVerificationOutput,
)
from academic_pipeline.research.ethics_validator import validate_ethics_checklist
from academic_pipeline.runtime.throttle import throttle_hooks
from academic_pipeline.tools.bibliography.doi import check_retraction, resolve_doi_metadata, verify_doi
from academic_pipeline.tools.bibliography.exa import web_fetch_exa, web_search_exa
from academic_pipeline.tools.bibliography.semantic_scholar import get_s2_paper_details, search_s2_by_title
from academic_pipeline.tools.integrity_tools import (
    check_plagiarism_heuristic,
    detect_ai_style_indicators,
    extract_claims,
)


_AGENTS_DIR = Path(__file__).parent / "specs"

agents: dict[str, Agent[PipelineDeps, Any]] = {
    "integrity_verification": Agent.from_file(
        _AGENTS_DIR / "integrity_verification.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(IntegrityVerificationOutput),
        capabilities=[throttle_hooks],
        tools=[
            extract_claims,
            check_plagiarism_heuristic,
            detect_ai_style_indicators,
            web_search_exa,
            web_fetch_exa,
            verify_doi,
            resolve_doi_metadata,
            check_retraction,
            search_s2_by_title,
            get_s2_paper_details,
        ],
    ),
    "compliance_check": Agent.from_file(
        _AGENTS_DIR / "compliance_check.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ComplianceReport),
        capabilities=[throttle_hooks],
    ),
    # PRD §6.1.T6 + §6.5.T1 — ethics_review agent moved here from research/
    # along with its YAML spec. The structured-checklist output_validator
    # (validate_ethics_checklist) enforces 12-item / canonical-order /
    # blocker-consistency invariants.
    "ethics_review": Agent.from_file(
        _AGENTS_DIR / "ethics_review.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(EthicsChecklist),
        capabilities=[throttle_hooks],
    ),
}

agents["ethics_review"].output_validator(validate_ethics_checklist)
