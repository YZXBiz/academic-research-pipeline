"""Review agent registry.

Centralises Agent.from_file() declarations and the default reviewer
sequence so that graph.py stays focused on node logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models.anthropic import AnthropicCompaction
from pydantic_ai_skills import SkillsCapability

from academic_pipeline.config import DEFAULT_CONFIG, SKILLS_DIRS
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.models.cascade import ClaimAuditReport
from academic_pipeline.models.novelty_report import (
    ClaimAssessment,
    ContributionClaimList,
)
from academic_pipeline.models.persona_review import PersonaReviewOutput
from academic_pipeline.models.review import (
    EditorialSynthesis,
    EICReview,
    FieldAnalysis,
    PeerReviewReport,
)
from academic_pipeline.runtime.throttle import throttle_hooks
from academic_pipeline.tools.bibliography.exa import web_fetch_exa, web_search_exa


_COMPACTION = AnthropicCompaction(token_threshold=DEFAULT_CONFIG.compaction_token_threshold)


_AGENTS_DIR = Path(__file__).parent / "specs"

agents: dict[str, Agent[PipelineDeps, Any]] = {
    "field_analyst": Agent.from_file(
        _AGENTS_DIR / "field_analyst.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(FieldAnalysis),
        capabilities=[throttle_hooks],
    ),
    "eic": Agent.from_file(
        _AGENTS_DIR / "eic.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(EICReview),
        capabilities=[throttle_hooks],
    ),
    "methodology_reviewer": Agent.from_file(
        _AGENTS_DIR / "methodology_reviewer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PeerReviewReport),
        capabilities=[throttle_hooks, SkillsCapability(directories=SKILLS_DIRS), _COMPACTION],  # pyright: ignore[reportArgumentType]
        tools=[web_search_exa, web_fetch_exa],
    ),
    "domain_reviewer": Agent.from_file(
        _AGENTS_DIR / "domain_reviewer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PeerReviewReport),
        capabilities=[throttle_hooks, SkillsCapability(directories=SKILLS_DIRS), _COMPACTION],  # pyright: ignore[reportArgumentType]
        tools=[web_search_exa, web_fetch_exa],
    ),
    "perspective_reviewer": Agent.from_file(
        _AGENTS_DIR / "perspective_reviewer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PeerReviewReport),
        capabilities=[throttle_hooks, SkillsCapability(directories=SKILLS_DIRS), _COMPACTION],  # pyright: ignore[reportArgumentType]
        tools=[web_search_exa, web_fetch_exa],
    ),
    "editorial_synthesizer": Agent.from_file(
        _AGENTS_DIR / "editorial_synthesizer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(EditorialSynthesis),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
    ),
    "claim_extractor": Agent.from_file(
        _AGENTS_DIR / "claim_extractor.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ContributionClaimList),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
    ),
    "claim_novelty_assessor": Agent.from_file(
        _AGENTS_DIR / "claim_novelty_assessor.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ClaimAssessment),
        capabilities=[throttle_hooks],
    ),
    "senior_gatekeeper_reviewer": Agent.from_file(
        _AGENTS_DIR / "senior_gatekeeper_reviewer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PersonaReviewOutput),
        capabilities=[throttle_hooks, SkillsCapability(directories=SKILLS_DIRS), _COMPACTION],  # pyright: ignore[reportArgumentType]
        tools=[web_search_exa, web_fetch_exa],
    ),
    "applied_practitioner_reviewer": Agent.from_file(
        _AGENTS_DIR / "applied_practitioner_reviewer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PersonaReviewOutput),
        capabilities=[throttle_hooks, SkillsCapability(directories=SKILLS_DIRS), _COMPACTION],  # pyright: ignore[reportArgumentType]
        tools=[web_search_exa, web_fetch_exa],
    ),
    "methodology_purist_reviewer": Agent.from_file(
        _AGENTS_DIR / "methodology_purist_reviewer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PersonaReviewOutput),
        capabilities=[throttle_hooks, SkillsCapability(directories=SKILLS_DIRS), _COMPACTION],  # pyright: ignore[reportArgumentType]
        tools=[web_search_exa, web_fetch_exa],
    ),
    "numerical_claims_auditor": Agent.from_file(
        _AGENTS_DIR / "numerical_claims_auditor.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ClaimAuditReport),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
    ),
}


# Default reviewer sequence: (reviewer_id, agent_key)
REVIEWER_AGENTS: list[tuple[str, str]] = [
    ("reviewer_1", "methodology_reviewer"),
    ("reviewer_2", "domain_reviewer"),
    ("reviewer_3", "perspective_reviewer"),
]


# Persona-anchored reviewer sequence (SCI Spec 5 Phase 1).
# Used by ParallelReviewerNode when config.persona_reviewers_enabled is true.
PERSONA_REVIEWER_AGENTS: list[tuple[str, str]] = [
    ("reviewer_1", "senior_gatekeeper_reviewer"),
    ("reviewer_2", "applied_practitioner_reviewer"),
    ("reviewer_3", "methodology_purist_reviewer"),
]
