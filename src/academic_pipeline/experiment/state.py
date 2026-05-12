"""State dataclass for the experiment subgraph."""
from __future__ import annotations

from dataclasses import dataclass, field

from academic_pipeline.models.experiment import (  # runtime needed for pydantic-graph serialization
    DesignBundle,
    DesignComparison,
    ExperimentAnalysis,
    ExperimentPlan,
    ExperimentResults,
    SelectedDesigns,
)


@dataclass
class ExperimentState:
    """State for the experiment subgraph.

    Carries research outputs as read-only input and accumulates experiment artifacts through the Design -> CodeGen ->
    Execution -> Analysis pipeline.
    """

    # Read-only inputs from research phase
    topic: str = ""
    run_id: str = ""
    rq_brief: str = ""
    methodology_blueprint: str = ""
    synthesis: str = ""

    # Predictor routing
    predictor_type: str = "tabular"

    # Experiment artifacts (populated by subgraph nodes)
    plan: ExperimentPlan | None = None
    generated_code: str | None = None
    results: ExperimentResults | None = None
    analysis: ExperimentAnalysis | None = None

    # Improvement loop tracking
    improvement_count: int = 0
    improvement_history: list[str] = field(default_factory=list)
    best_results: ExperimentResults | None = None
    best_code: str | None = None

    # Retry tracking
    retry_count: int = 0
    error_history: list[str] = field(default_factory=list)

    # Messages for tracing
    messages: list[dict[str, str]] = field(default_factory=list)

    # Judge loop tracking
    judge_feedback: str | None = None
    judge_further_experiments: list[str] = field(default_factory=list)
    judge_iteration: int = 0

    # Exploration breadth (Spec 7) — populated only when
    # config.exploration_breadth_enabled=True
    design_bundle: DesignBundle | None = None
    selected_designs: SelectedDesigns | None = None
    design_comparison: DesignComparison | None = None
