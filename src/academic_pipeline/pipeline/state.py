"""State dataclass for the PydanticAI pipeline orchestrator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Annotated, Any, ClassVar

from pydantic import Field

from academic_pipeline.core.enums import (  # runtime needed for pydantic-graph serialization
    PipelineStatus,
    Stage,
)
from academic_pipeline.models.cascade import CascadeResult  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.chain import (  # runtime needed for pydantic-graph serialization
    DevelopmentChain,
    ThesisStatement,
)
from academic_pipeline.models.citation_grounding import (  # runtime needed for pydantic-graph serialization
    CitationGroundingReport,
)
from academic_pipeline.models.experiment import (  # runtime needed for pydantic-graph serialization
    ExperimentAnalysis,
    ExperimentClassification,
    ExperimentPlan,
    ExperimentResults,
    FigureArtifact,
)
from academic_pipeline.models.integrity import MaterialPassport  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.novelty_gate import NoveltyGateResult  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.novelty_report import NoveltyReport  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.numerical import NumericalStore  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.persona_review import (
    PersonaReviewOutput,  # runtime needed for pydantic-graph serialization
)
from academic_pipeline.models.research import (  # runtime needed for pydantic-graph serialization
    Bibliography,
    MethodologyBlueprint,
    RQBrief,
    SynthesisReport,
)
from academic_pipeline.models.review import ResponseToReviewers  # runtime needed for pydantic-graph serialization
from academic_pipeline.models.writing import (  # runtime needed for pydantic-graph serialization
    ArgumentBlueprint,
    FigurePackage,
    PaperConfig,
    PaperDraft,
    PaperOutline,
    StyleProfile,
)


logger = logging.getLogger(__name__)


# PRD §6.9.T1 — PipelineState schema version. Bump when a backward-incompatible
# field rename / removal lands. SqliteStatePersistence.load_pipeline_state
# rejects mismatched values with PRS001 IncompatibleStateError; operators clean
# up via `tools/cleanup_state.py --before <new-version>` (PRD §6.9.T5).
PIPELINE_STATE_SCHEMA_VERSION = 1


@dataclass
class PipelineState:
    """Top-level pipeline state shared across the orchestrator graph.

    Mutable dataclass used by pydantic-graph's ``GraphRunContext``.
    """

    STAGE_REINFORCEMENTS: ClassVar[dict[Stage, str]] = {
        Stage.PRE_INTEGRITY: (
            "[REINFORCEMENT] Integrity check is MANDATORY and cannot be skipped. "
            "Every reference must reach VERIFIED or NOT_FOUND — no gray zone. "
            "Zero tolerance for fabricated citations."
        ),
        Stage.REVIEW: (
            "[REINFORCEMENT] Reviewers are READ-ONLY — they never modify the manuscript. "
            "DA critical findings block Accept decisions. "
            "Anti-sycophancy: no concession below 4/5 rebuttal score."
        ),
        Stage.FINAL_INTEGRITY: (
            "[REINFORCEMENT] Final integrity is FRESH full verification — not a delta check. "
            "Phase E: 100% claim verification required. "
            "Zero SERIOUS/MEDIUM issues to proceed."
        ),
    }

    # Core identifiers
    topic: str = ""
    current_stage: Stage | str = ""
    pipeline_status: PipelineStatus | str = ""
    run_id: str = ""
    # PRD §6.9.T1 — schema version stamp. Persisted to SQLite; SqliteStatePersistence
    # raises PRS001 IncompatibleStateError on mismatch.
    _schema_version: int = PIPELINE_STATE_SCHEMA_VERSION

    # Research handoff data
    rq_brief: RQBrief | None = None
    methodology_blueprint: MethodologyBlueprint | None = None
    bibliography: Bibliography | None = None
    synthesis: SynthesisReport | None = None
    # Chain-of-Ideas KG (Spec 2 Phase 1) — populated when
    # config.chain_of_ideas_enabled is true. None when flag off.
    chain: DevelopmentChain | None = None
    thesis: ThesisStatement | None = None

    # Writing handoff data
    paper_config: PaperConfig | None = None
    paper_outline: PaperOutline | None = None
    argument_blueprint: ArgumentBlueprint | None = None
    paper_draft: PaperDraft | None = None
    figure_package: FigurePackage | None = None
    style_profile: StyleProfile | None = None
    # Semantic citation-grounding report from the writing subgraph. Consumed
    # by the integrity phase: critical mismatches force an integrity FAIL.
    citation_grounding: CitationGroundingReport | None = None

    # Review handoff data
    review_report: dict[str, Any] = field(default_factory=dict)
    revision_roadmap: dict[str, Any] = field(default_factory=dict)
    response_to_reviewers: ResponseToReviewers | None = None

    # Integrity handoff data
    integrity_report: dict[str, Any] = field(default_factory=dict)
    compliance_reports: dict[str, Any] = field(default_factory=dict)

    # Provenance
    material_passport: MaterialPassport | None = None
    monitoring_config: dict[str, Any] = field(default_factory=dict)

    # Loop counters
    integrity_fix_count: int = 0
    consecutive_continues: int = 0

    # Messages
    messages: list[dict[str, str]] = field(default_factory=list)

    # Stage tracking
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Version labels
    version_labels: dict[str, str] = field(default_factory=dict)

    # Human-in-the-loop

    # Score trajectory
    score_history: list[dict[str, int]] = field(default_factory=list)
    score_trajectory_flags: list[str] = field(default_factory=list)

    # LaTeX output
    latex_source: str = ""
    bib_source: str = ""
    pdf_bytes: Annotated[bytes, Field(exclude=True)] = b""
    output_format: str = "latex"

    # Revision support
    revision_instructions: str = ""

    # Ephemeral agent communication
    editorial_decision: str = ""

    # Experiment handoff data
    experiment_classification: ExperimentClassification | None = None
    experiment_plan: ExperimentPlan | None = None
    experiment_code: str | None = None
    experiment_results: ExperimentResults | None = None
    experiment_analysis: ExperimentAnalysis | None = None
    experiment_figures: list[FigureArtifact] = field(default_factory=list)
    experiment_fix_count: int = 0
    experiment_error_history: list[str] = field(default_factory=list)

    # Traceability layer (SCI port)
    numerical_store: NumericalStore = field(default_factory=NumericalStore)

    # Novelty gate (SCI Spec 3 Phase 1)
    novelty_gate_result: NoveltyGateResult | None = None
    """Result of the pre-research Semantic Scholar novelty check, if enabled."""

    # Point-wise novelty reviewer (SCI Spec 4 Phase 1)
    novelty_report: NoveltyReport | None = None
    """Result of the per-claim novelty assessment in the review subgraph, if enabled."""

    # Persona-anchored reviewer panel (SCI Spec 5 Phase 1)
    persona_reviews: list[PersonaReviewOutput] = field(default_factory=list)
    """Outputs of the 3 persona-anchored reviewers when persona_reviewers_enabled.
    Empty list when the flag is off."""

    # Cascaded reviewer pipeline (SCI Spec 6 Phase 1)
    cascade_result: CascadeResult | None = None
    """Result of the 4-stage cascaded review when cascaded_review_enabled.
    None when the flag is off."""

    copilot_comments: dict[str, str] = field(default_factory=dict)
    """Optional 1-sentence comments collected at copilot checkpoints, keyed by checkpoint name
    ("post_intake", "post_experiment_design", "post_first_draft"). Empty when --copilot off."""

    def set_stage(self, stage: Stage) -> None:
        """Update current stage and mark the previous one completed.

        Merges status into existing stage dicts to preserve completed_nodes
        and other tracking data accumulated during stage execution.
        """
        if self.current_stage and self.current_stage != stage:
            prev = self.current_stage.value if isinstance(self.current_stage, Stage) else self.current_stage
            prev_data = self.stages.get(prev, {})
            prev_data["status"] = "completed"
            self.stages[prev] = prev_data
        self.current_stage = stage
        new_data = self.stages.get(stage.value, {})
        new_data["status"] = "in_progress"
        self.stages[stage.value] = new_data

    def inject_reinforcement(self, stage: Stage) -> None:
        """Append a stage-transition reinforcement message to counteract instruction drift."""
        reinforcement = self.STAGE_REINFORCEMENTS.get(stage)
        if reinforcement:
            self.messages.append({"role": "system", "content": reinforcement})

    def summarize_integrity_issues(self) -> str:
        """Extract a short summary of issues from the integrity report."""
        issues = self.integrity_report.get("issues", [])
        if isinstance(issues, list) and issues:
            return "; ".join(str(i) for i in issues[:5])
        reason = self.integrity_report.get("reason", "")
        if reason:
            return str(reason)
        raw = self.integrity_report.get("raw", "")
        if raw:
            return str(raw)[:200]
        return str(self.integrity_report)[:200]
