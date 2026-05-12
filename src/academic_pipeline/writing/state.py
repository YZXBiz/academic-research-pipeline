"""State dataclass for the writing subgraph."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Annotated, Any

# Runtime imports — pydantic-graph snapshot serialization needs these at
# runtime; moving them under TYPE_CHECKING breaks resume.
from pydantic import Field  # noqa: TCH002

from academic_pipeline.models.chain import (
    DevelopmentChain,  # noqa: TCH001
    ThesisStatement,  # noqa: TCH001
)
from academic_pipeline.models.experiment import (
    ExperimentAnalysis,  # noqa: TCH001
    ExperimentResults,  # noqa: TCH001
    FigureArtifact,  # noqa: TCH001
)
from academic_pipeline.models.numerical import NumericalStore
from academic_pipeline.models.research import (
    Bibliography,  # noqa: TCH001
    RQBrief,  # noqa: TCH001
    SynthesisReport,  # noqa: TCH001
)
from academic_pipeline.models.review import (
    FigureVerificationReport,  # noqa: TCH001
    ResponseToReviewers,  # noqa: TCH001
)
from academic_pipeline.models.writing import (
    ArgumentBlueprint,  # noqa: TCH001
    FigurePackage,  # noqa: TCH001
    PaperConfig,  # noqa: TCH001
    PaperDraft,  # noqa: TCH001
    PaperOutline,  # noqa: TCH001
    Section,  # noqa: TCH001
    SectionSpec,  # noqa: TCH001
    StyleProfile,  # noqa: TCH001
)
from academic_pipeline.runtime.score_trajectory import (
    check_early_stop,
    compute_deltas,
    detect_regression,
    parse_scores_from_review,
)


logger = logging.getLogger(__name__)


@dataclass
class WritingState:
    """State for the writing subgraph.

    Consolidates fields from WritingInput, WritingOutput, and ephemeral writing-related keys from PipelineState into a
    single dataclass.
    """

    topic: str = ""
    rq_brief: RQBrief | None = None
    bibliography: Bibliography | None = None
    synthesis: SynthesisReport | None = None
    # PRD §6.1.T8 — Chain-of-Ideas + thesis handoff from research subgraph.
    # Populated by WritePhaseNode from PipelineState.{chain,thesis}. Both stay
    # None when chain_of_ideas_enabled is false (legacy escape hatch).
    chain: DevelopmentChain | None = None
    thesis: ThesisStatement | None = None
    paper_draft: PaperDraft | None = None
    paper_config: PaperConfig | None = None
    paper_outline: PaperOutline | None = None
    argument_blueprint: ArgumentBlueprint | None = None
    figure_package: FigurePackage | None = None
    figure_verification: FigureVerificationReport | None = None
    response_to_reviewers: ResponseToReviewers | None = None
    revision_roadmap: dict[str, Any] = field(default_factory=dict)
    style_profile: StyleProfile | None = None
    review_report: dict[str, Any] = field(default_factory=dict)
    literature_strategy: dict[str, Any] = field(default_factory=dict)
    formatted_output: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, str]] = field(default_factory=list)

    # Score trajectory
    score_history: list[dict[str, int]] = field(default_factory=list)
    score_trajectory_flags: list[str] = field(default_factory=list)

    # Pre-revision snapshot for regression revert
    pre_revision_draft: PaperDraft | None = None

    # Parallel section drafting
    section_specs: list[SectionSpec] = field(default_factory=list)
    section_drafts: list[Section] = field(default_factory=list)

    # Ephemeral inter-node
    internal_review: str = ""
    citation_audit: dict[str, Any] = field(default_factory=dict)
    abstract_result: dict[str, Any] = field(default_factory=dict)
    peer_review_round: int = 0
    needs_revision: bool = False

    # LaTeX output
    latex_source: str = ""
    bib_source: str = ""
    pdf_bytes: Annotated[bytes, Field(exclude=True)] = b""
    output_format: str = "latex"

    # Experiment data (optional — present when experiment phase ran)
    experiment_results: ExperimentResults | None = None
    experiment_analysis: ExperimentAnalysis | None = None
    experiment_figures: list[FigureArtifact] = field(default_factory=list)
    methodology_blueprint: str = ""

    # Traceability layer (SCI port) — populated upstream by AnalysisNode
    numerical_store: NumericalStore = field(default_factory=NumericalStore)

    def record_scores(self, report_text: str) -> tuple[list[str], dict[str, int], bool]:
        """Parse scores from a review, record to history, check for regression/early-stop.

        Returns:
            (regressed_dimensions, deltas, early_stop)
        """
        scores = parse_scores_from_review(report_text)
        if not scores:
            return [], {}, False

        round_scores = {"round": self.peer_review_round, **scores}
        self.score_history.append(round_scores)
        logger.info("Score trajectory: recorded scores for round %d", self.peer_review_round)

        if len(self.score_history) < 2:
            return [], {}, False

        prev = self.score_history[-2]
        deltas = compute_deltas(scores, prev)

        regressions = detect_regression(deltas)
        if regressions:
            flag = f"round_{self.peer_review_round}_regression: {', '.join(regressions)}"
            self.score_trajectory_flags.append(flag)
            logger.warning("Score trajectory regression in: %s", ", ".join(regressions))
            return regressions, deltas, False

        has_p0 = "critical" in report_text.lower()
        if check_early_stop(deltas, has_p0=has_p0):
            logger.info("Score trajectory: early-stop — scores converged with no P0 issues")
            self.score_trajectory_flags.append(f"round_{self.peer_review_round}_early_stop")
            return [], deltas, True

        return [], deltas, False
