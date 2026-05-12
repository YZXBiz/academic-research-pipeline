"""Experiment-phase domain models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ExperimentClassification",
    "DatasetSpec",
    "DatasetVerificationResult",
    "MethodSpec",
    "ExperimentPlan",
    "StatisticalTest",
    "FigureArtifact",
    "MultiSeedMetric",
    "ExperimentResults",
    "BaselineComparison",
    "ExperimentAnalysis",
    "FigureReview",
    "FigureReviewResult",
    "PlanAlignmentResult",
    "DesignAlternative",
    "DesignBundle",
    "DesignScore",
    "SelectedDesigns",
    "DesignComparison",
    "WorkspaceFile",
    "WorkspaceFiles",
]


class ExperimentClassification(BaseModel):
    """Classifier output: does this topic need computational experiments?"""

    model_config = ConfigDict(frozen=True)

    needs_experiments: bool
    reasoning: str
    predictor_type: Literal["tabular", "timeseries", "multimodal"] | None = None
    suggested_experiment_type: str | None = None
    suggested_datasets: list[str] = Field(default_factory=list)


class DatasetSpec(BaseModel):
    """Specification for a dataset to use in an experiment."""

    model_config = ConfigDict(frozen=True)

    name: str
    source: str
    download_instruction: str
    expected_shape: str
    target_column: str | None = None


class DatasetVerificationResult(BaseModel):
    """Result of verifying dataset URLs are reachable."""

    model_config = ConfigDict(frozen=True)

    all_verified: bool
    failed_datasets: list[str] = Field(default_factory=list)
    verified_datasets: list[str] = Field(default_factory=list)


class MethodSpec(BaseModel):
    """Specification for an ML method (baseline or proposed)."""

    model_config = ConfigDict(frozen=True)

    name: str
    implementation: str
    is_baseline: bool


class ExperimentPlan(BaseModel):
    """Structured experiment design produced by the design agent."""

    model_config = ConfigDict(frozen=True)

    research_question: str
    hypothesis: str
    experiment_type: str
    dataset_sources: list[DatasetSpec]
    baseline_methods: list[MethodSpec]
    proposed_methods: list[MethodSpec]
    evaluation_metrics: list[str]
    success_criteria: str
    required_figures: list[str] = Field(default_factory=list)
    estimated_runtime_minutes: int = 10
    python_packages: list[str] = Field(default_factory=list)


class StatisticalTest(BaseModel):
    """Result of a statistical significance test between methods."""

    model_config = ConfigDict(frozen=True)

    test_name: str
    p_value: float
    significant: bool
    effect_size: float | None = None


class FigureArtifact(BaseModel):
    """A generated figure with metadata for paper integration."""

    model_config = ConfigDict(frozen=True)

    figure_type: str
    filename: str
    caption: str
    data_base64: str
    width_inches: float = 8.0
    height_inches: float = 6.0


class MultiSeedMetric(BaseModel):
    """A metric aggregated across multiple random seeds."""

    model_config = ConfigDict(frozen=True)

    mean: float
    std: float = 0.0
    values: list[float] = Field(default_factory=list)


class ExperimentResults(BaseModel):
    """Raw results from experiment execution.

    Accepts both flat metrics (dict[str, float]) and multi-seed
    metrics (dict[str, MultiSeedMetric]) per method.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    success: bool = True
    metrics: dict[str, dict[str, float | MultiSeedMetric]]
    cv_scores: dict[str, list[float]] = Field(default_factory=dict)
    statistical_tests: dict[str, StatisticalTest | dict[str, Any]] = Field(default_factory=dict)
    execution_time_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    code: str = ""
    figures: list[FigureArtifact | str] = Field(default_factory=list)
    data_summary: str = ""
    retries_used: int = 0


class BaselineComparison(BaseModel):
    """Structured comparison between our results and a baseline."""

    model_config = ConfigDict(frozen=True)

    baseline_name: str
    source: str
    metric_comparison: dict[str, tuple[float, float]]
    where_we_agree: str
    where_we_differ: str
    why_we_differ: str
    statistical_significance: str | None = None


class ExperimentAnalysis(BaseModel):
    """Deep interpretation of experiment results for paper writing."""

    model_config = ConfigDict(frozen=True)

    results_interpretation: str
    baseline_comparisons: list[BaselineComparison] = Field(default_factory=list)
    domain_implications: str = ""
    domain_theory_connection: str = ""
    alternative_explanations: list[str] = Field(default_factory=list)
    shap_interpretation: str | None = None
    limitations: list[str] = Field(default_factory=list)
    threats_to_validity: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    figure_references: list[str] = Field(default_factory=list)
    suggested_paper_structure: str = "imrad"


class FigureReview(BaseModel):
    """Review of a single generated figure."""

    model_config = ConfigDict(frozen=True)

    filename: str
    valid: bool
    issues: list[str] = Field(default_factory=list)


class FigureReviewResult(BaseModel):
    """Aggregated figure review result."""

    model_config = ConfigDict(frozen=True)

    all_valid: bool
    reviews: list[FigureReview] = Field(default_factory=list)


class PlanAlignmentResult(BaseModel):
    """Result of checking code against experiment plan."""

    model_config = ConfigDict(frozen=True)

    aligned: bool
    missing_methods: list[str] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)
    missing_datasets: list[str] = Field(default_factory=list)
    missing_figures: list[str] = Field(default_factory=list)
    missing_statistical_tests: bool = False
    missing_cross_validation: bool = False


class DesignAlternative(BaseModel):
    """One candidate experiment design within a DesignBundle.

    Wraps a full ExperimentPlan with a stable design_id (D1, D2, ...) and a
    short rationale explaining what hypothesis it tests and what tradeoff it
    makes versus the other alternatives in the bundle.
    """

    model_config = ConfigDict(frozen=True)

    design_id: str = Field(description="Stable identifier within bundle (D1, D2, ...)")
    design: ExperimentPlan = Field(description="Full ExperimentPlan for this alternative")
    rationale: str = Field(
        description="1-paragraph (3-5 sentences) explaining what hypothesis this design tests "
        "and what tradeoff it makes versus the other alternatives."
    )


class DesignBundle(BaseModel):
    """N candidate experiment designs produced by the bundle designer.

    Designs must use diverse method families (not minor hyperparameter
    variants) so the scorer can meaningfully discriminate between them.
    """

    model_config = ConfigDict(frozen=True)

    alternatives: list[DesignAlternative] = Field(
        description="N candidate designs, default 4. Method families should be diverse."
    )


class DesignScore(BaseModel):
    """Per-alternative score with rubric breakdown and weighted overall.

    All sub-scores are 1-10 (higher is better). The risk_score is inverted so
    higher = lower risk, keeping monotonicity with overall_score.
    """

    model_config = ConfigDict(frozen=True)

    design_id: str
    data_availability_score: float = Field(ge=1.0, le=10.0)
    methodological_fit_score: float = Field(ge=1.0, le=10.0)
    expected_discriminative_power: float = Field(ge=1.0, le=10.0)
    risk_score: float = Field(ge=1.0, le=10.0, description="10 = low risk, 1 = high risk (inverted)")
    overall_score: float = Field(ge=1.0, le=10.0, description="Weighted composite, 1-10")
    selection_rationale: str


class SelectedDesigns(BaseModel):
    """Outcome of DesignSelectionNode: top-K designs plus all scores."""

    model_config = ConfigDict(frozen=True)

    selected: list[DesignAlternative] = Field(description="Top K designs by overall_score")
    not_selected: list[DesignAlternative] = Field(description="Designs scored but not chosen")
    scores: list[DesignScore] = Field(description="All N scores for transparency")


class DesignComparison(BaseModel):
    """Cross-design comparison artifact for the paper's Discussion section.

    In Phase 1 only the highest-scoring design is actually run, so
    selected_results contains a single entry. Phase 2 will fan out to K
    parallel runs and populate selected_results with multiple entries.
    """

    model_config = ConfigDict(frozen=True)

    selected_results: dict[str, ExperimentResults] = Field(
        description="design_id -> ExperimentResults for each design that was actually run"
    )
    comparison_table: str = Field(description="Markdown table of method x metric across designs")
    discussion_paragraph: str = Field(
        description="One paragraph for the paper's Discussion section explaining alternatives "
        "considered, choice made, and tradeoffs."
    )
    chosen_design_id: str = Field(description="design_id whose results become the primary findings")


class WorkspaceFile(BaseModel):
    """One file the config_writer agent writes into the Dagster workspace.

    The agent emits a list of these — config.yaml plus N Python @asset
    modules under assets/experiment/. Path is relative to the workspace
    root so the writer can place each file deterministically.
    """

    model_config = ConfigDict(frozen=True)

    path: str = Field(
        description="Path relative to workspace root, e.g. 'config.yaml' or "
        "'src/pipeline/assets/experiment/cluster_assignments.py'."
    )
    content: str = Field(description="Full file contents. No markdown fences.")


class WorkspaceFiles(BaseModel):
    """Bundle of files the config_writer agent produces for one experiment."""

    model_config = ConfigDict(frozen=True)

    files: list[WorkspaceFile] = Field(
        min_length=2,
        description="At minimum: 1 config.yaml + 1 generated @asset module.",
    )
