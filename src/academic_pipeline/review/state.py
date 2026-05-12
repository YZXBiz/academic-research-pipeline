"""State dataclass for the review subgraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from academic_pipeline.core.enums import (
    EditorialDecision,  # runtime needed for pydantic-graph serialization
)
from academic_pipeline.models.cascade import CascadeResult  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.novelty_report import NoveltyReport  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.persona_review import PersonaReviewOutput  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.review import ResponseToReviewers  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.writing import PaperDraft  # runtime needed for pydantic-graph serialization


@dataclass
class ReviewState:
    """State for the review subgraph.

    Consolidates fields from ReviewInput, ReviewOutput, and ephemeral review-related keys from PipelineState into a
    single dataclass for use with PydanticAI agents and pydantic-graph nodes.
    """

    paper_draft: PaperDraft | None = None
    review_report: dict[str, Any] = field(default_factory=dict)
    revision_roadmap: dict[str, Any] = field(default_factory=dict)
    response_to_reviewers: ResponseToReviewers | None = None
    messages: list[dict[str, str]] = field(default_factory=list)

    # Reviewer dispatch
    reviewer_reports: list[dict[str, Any]] = field(default_factory=list)
    current_reviewer_id: str = ""
    current_reviewer_agent: str = ""

    # Routing
    editorial_decision: EditorialDecision | None = None
    needs_coaching: bool = False

    # Point-wise novelty reviewer (SCI Spec 4 Phase 1) — populated when
    # config.pointwise_novelty_enabled is true. None when flag off.
    novelty_report: NoveltyReport | None = None

    # Persona-anchored reviewer panel (SCI Spec 5 Phase 1) — populated when
    # config.persona_reviewers_enabled is true. Empty list when flag off.
    persona_reviews: list[PersonaReviewOutput] = field(default_factory=list)

    # Cascaded reviewer pipeline (SCI Spec 6 Phase 1) — populated when
    # config.cascaded_review_enabled is true. None when flag off.
    cascade_result: CascadeResult | None = None

    # HITL
