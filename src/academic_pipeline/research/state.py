"""State dataclass for the research subgraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Runtime imports — pydantic-graph snapshot serialization needs these at
# runtime; moving them under TYPE_CHECKING breaks resume.
from academic_pipeline.core.enums import Verdict  # noqa: TCH001
from academic_pipeline.models.chain import (
    DevelopmentChain,  # noqa: TCH001
    ThesisStatement,  # noqa: TCH001
)
from academic_pipeline.models.research import (
    Bibliography,  # noqa: TCH001
    IndependentVerificationReport,  # noqa: TCH001
    MethodologyBlueprint,  # noqa: TCH001
    RQBrief,  # noqa: TCH001
    SynthesisReport,  # noqa: TCH001
)
from academic_pipeline.models.review import EditorReview  # noqa: TCH001


@dataclass
class ResearchState:
    """State for the research subgraph.

    Consolidates fields from ResearchInput, ResearchOutput, and ephemeral research-related keys from PipelineState into
    a single dataclass.
    """

    topic: str = ""
    rq_brief: RQBrief | None = None
    methodology_blueprint: MethodologyBlueprint | None = None
    bibliography: Bibliography | None = None
    synthesis: SynthesisReport | None = None
    # PRD §6.1.T7 — knowledge_graph field removed (KnowledgeGraph model + node deleted).
    # Chain-of-Ideas KG (Spec 2) — populated by ChainOfIdeasNode when
    # config.chain_of_ideas_enabled is true (default). The Phase 4 reorder
    # makes thesis a required input to SynthesisNode.
    chain: DevelopmentChain | None = None
    thesis: ThesisStatement | None = None
    independent_verification_report: IndependentVerificationReport | None = None
    review_report: dict[str, Any] = field(default_factory=dict)
    monitoring_config: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, str]] = field(default_factory=list)

    # Revision tracking
    needs_revision: bool = False

    # EIC / Ethics
    eic_review: str = ""
    eic_review_structured: EditorReview | None = None
    ethics_verdict: Verdict | None = None
