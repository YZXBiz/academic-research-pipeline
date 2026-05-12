"""Research-phase domain models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from academic_pipeline.models.shared import (
    FlaggedSeverity,
    QualityTier,
    Source,
)


__all__ = [
    "FINERScores",
    "Scope",
    "RQBrief",
    "SearchStrategy",
    "PRISMACounts",
    "Bibliography",
    "Theme",
    "Debate",
    "SynthesisReport",
    "SourceQualityGrade",
    "FlaggedSource",
    "SourceVerificationReport",
    "ResearchReport",
    "ResearchParadigm",
    "ResearchMethod",
    "DataStrategy",
    "AnalyticalFramework",
    "ValidityCriterion",
    "DesignLimitation",
    "IRBPlan",
    "Preregistration",
    "MethodologyBlueprint",
    "ClaimVerification",
    "IndependentVerificationReport",
]


class FINERScores(BaseModel):
    """FINER framework scores for research question evaluation."""

    model_config = ConfigDict(frozen=True)

    feasible: int = Field(ge=3, le=5, description="Answerable with available methods/data? 3=adequate, 5=strong")
    interesting: int = Field(
        ge=3, le=5, description="Addresses a genuine puzzle or contradiction? 3=adequate, 5=strong"
    )
    novel: int = Field(ge=3, le=5, description="Offers new perspective, method, or evidence? 3=adequate, 5=strong")
    ethical: int = Field(ge=3, le=5, description="Ethical concerns? 3=some concerns, 5=no concerns")
    relevant: int = Field(ge=3, le=5, description="Informs policy, practice, or theory? 3=adequate, 5=strong")

    @property
    def average(self) -> float:
        """Average FINER score across all criteria."""
        scores = [self.feasible, self.interesting, self.novel, self.ethical, self.relevant]
        return sum(scores) / len(scores)


class Scope(BaseModel):
    """Boundary definition for a research project's domain, timeframe, and population."""

    model_config = ConfigDict(frozen=True)

    in_scope: list[str]
    out_of_scope: list[str]
    domain: str
    timeframe: str
    geography: str
    population: str


class RQBrief(BaseModel):
    """Research question brief with FINER scores, scope, and methodology."""

    model_config = ConfigDict(frozen=True)

    research_question: str
    sub_questions: list[str] = Field(min_length=2, max_length=5)
    finer_scores: FINERScores
    scope: Scope
    methodology_type: Literal["qualitative", "quantitative", "mixed"]
    theoretical_framework: str
    keywords: list[str] = Field(min_length=5, max_length=10)

    hypothesis: str | None = None
    exclusion_criteria: list[str] | None = None
    stakeholders: list[str] | None = None
    ethical_flags: list[str] | None = None


class SearchStrategy(BaseModel):
    """Literature search parameters including databases, keywords, and filters."""

    model_config = ConfigDict(frozen=True)

    databases: list[str]
    keywords: list[str]
    inclusion_criteria: list[str]
    exclusion_criteria: list[str]
    date_range: str


class PRISMACounts(BaseModel):
    """PRISMA flow diagram counts for systematic review screening stages."""

    model_config = ConfigDict(frozen=True)

    identified: int = Field(ge=0)
    screened: int = Field(ge=0)
    eligible: int = Field(ge=0)
    included: int = Field(ge=0)

    @model_validator(mode="after")
    def check_funnel(self) -> PRISMACounts:
        """Validate that counts form a decreasing funnel: identified >= screened >= eligible >= included."""
        if not (self.identified >= self.screened >= self.eligible >= self.included):
            raise ValueError("PRISMA counts must form a decreasing funnel")
        return self


class Bibliography(BaseModel):
    """Collection of sources with search strategy and coverage assessment."""

    model_config = ConfigDict(frozen=True)

    sources: list[Source]
    search_strategy: SearchStrategy
    coverage_assessment: str
    minimum_sources: int = Field(ge=1)

    prisma_counts: PRISMACounts | None = None


class Theme(BaseModel):
    """Thematic finding from literature synthesis with supporting evidence."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    supporting_sources: list[str]
    contradicting_sources: list[str] = Field(default_factory=list)
    strength: Literal["strong", "moderate", "emerging"]


class Debate(BaseModel):
    """Scholarly debate between two opposing positions with source evidence."""

    model_config = ConfigDict(frozen=True)

    position_a: str
    position_b: str
    sources_a: list[str]
    sources_b: list[str]
    evidence_balance: str


class SynthesisReport(BaseModel):
    """Literature synthesis output with themes, gaps, debates, and recommendations."""

    model_config = ConfigDict(frozen=True)

    themes: list[Theme] = Field(min_length=3, max_length=7)
    research_gaps: list[str]
    key_debates: list[Debate]
    methodology_recommendations: list[str]
    theoretical_implications: list[str]
    consensus_areas: list[str]


# PRD §6.1.T7 — KnowledgeGraph + SourceRelationship + ResearchCluster +
# RelationType deleted (orphan after the legacy KnowledgeGraphNode was retired).


class SourceQualityGrade(BaseModel):
    """Quality grade for a single source in the bibliography."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(description="Identifier of the source being graded")
    quality_tier: QualityTier = Field(description="Assessed quality tier of the source")
    peer_reviewed: bool = Field(description="Whether the source is peer-reviewed")
    impact_factor: float | None = Field(default=None, description="Journal impact factor if available")
    notes: str = Field(default="", description="Additional quality assessment notes")


class FlaggedSource(BaseModel):
    """A source flagged during verification for quality or integrity concerns."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(description="Identifier of the flagged source")
    reason: str = Field(description="Why the source was flagged")
    severity: FlaggedSeverity = Field(description="Low, Medium, High, or Critical severity of the concern")
    recommendation: str = Field(description="Suggested action (e.g., remove, replace, add caveat)")


class SourceVerificationReport(BaseModel):
    """Structured output from the source verification agent."""

    model_config = ConfigDict(frozen=True)

    sources_reviewed: int = Field(ge=0, description="Total number of sources reviewed")
    verified_count: int = Field(ge=0, description="Number of sources that passed verification")
    flagged_count: int = Field(ge=0, description="Number of sources flagged for concerns")
    rejected_count: int = Field(ge=0, description="Number of sources recommended for removal")
    source_quality_matrix: list[SourceQualityGrade] = Field(
        default_factory=list, description="Quality grades for each reviewed source"
    )
    flagged_sources: list[FlaggedSource] = Field(
        default_factory=list, description="Sources flagged during verification"
    )
    predatory_alerts: list[str] = Field(default_factory=list, description="Predatory publisher alerts")
    retraction_flags: list[str] = Field(default_factory=list, description="Retracted or corrected source flags")
    coi_disclosures: list[str] = Field(default_factory=list, description="Conflict-of-interest disclosures detected")
    verification_limitations: str = Field(default="", description="Limitations of the verification process")


class ResearchReport(BaseModel):
    """Structured output from the report compiler agent."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(description="Full compiled research report in markdown")
    word_count: int = Field(ge=0, description="Total word count of the report")
    sections_completed: list[str] = Field(description="List of section headings completed")
    unresolved_issues: list[str] = Field(default_factory=list, description="Issues that remain unresolved")
    ai_disclosure: str = Field(default="", description="AI usage disclosure statement")


class ResearchParadigm(BaseModel):
    """Selected research paradigm with justification."""

    model_config = ConfigDict(frozen=True)

    selected: str = Field(description="e.g., Positivist, Interpretivist, Pragmatist, Critical")
    justification: str = Field(description="Why this paradigm fits the RQ (ontological/epistemological alignment)")


class ResearchMethod(BaseModel):
    """Selected research method with justification."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    source_type: str = Field(alias="type", description="Qualitative, quantitative, or mixed")
    specific_method: str = Field(description="e.g., comparative case study, regression analysis")
    justification: str = Field(description="Why this method answers the RQ — cite the question, not popularity")


class DataStrategy(BaseModel):
    """Data collection strategy."""

    model_config = ConfigDict(frozen=True)

    data_type: str = Field(description="Primary, secondary, or both")
    sources: str = Field(description="Specific databases, populations, documents, or archives")
    sampling: str = Field(description="Sampling strategy and rationale (power analysis / saturation)")
    time_frame: str = Field(description="Data collection period or date range")


class AnalyticalFramework(BaseModel):
    """Analytical approach and tools."""

    model_config = ConfigDict(frozen=True)

    technique: str = Field(description="e.g., thematic analysis, regression, SWOT, grounded theory coding")
    steps: str = Field(description="Ordered analytical procedure from raw data to findings")
    tools: str = Field(description="Software and frameworks (e.g., NVivo, SPSS, R, Atlas.ti)")


class ValidityCriterion(BaseModel):
    """Single validity/reliability criterion and strategy to ensure it."""

    model_config = ConfigDict(frozen=True)

    criterion: str = Field(description="e.g., internal validity, credibility, transferability")
    strategy: str = Field(description="Specific strategy to ensure this criterion is met")


class DesignLimitation(BaseModel):
    """Known limitation and its mitigation strategy."""

    model_config = ConfigDict(frozen=True)

    limitation: str = Field(description="Known methodological limitation")
    mitigation: str = Field(description="How the limitation will be addressed or acknowledged")


class IRBPlan(BaseModel):
    """IRB review plan for research involving human subjects."""

    model_config = ConfigDict(frozen=True)

    irb_level: str = Field(description="Exempt, Expedited, or Full Board")
    informed_consent: str = Field(description="Consent strategy and form elements")
    data_deidentification: str = Field(description="De-identification methods and data retention procedures")
    irb_timeline_weeks: int = Field(description="Estimated weeks for IRB review")


class Preregistration(BaseModel):
    """Preregistration recommendation."""

    model_config = ConfigDict(frozen=True)

    recommended: bool = Field(description="Whether preregistration is recommended for this study")
    platform: str = Field(description="OSF, PROSPERO, AsPredicted, or N/A")
    status: str = Field(description="Planned, Completed, or Not applicable")


class MethodologyBlueprint(BaseModel):
    """Complete methodology blueprint produced by the Research Architect agent."""

    model_config = ConfigDict(frozen=True)

    paradigm: ResearchParadigm
    method: ResearchMethod
    data_strategy: DataStrategy
    analytical_framework: AnalyticalFramework
    validity_criteria: list[ValidityCriterion]
    limitations: list[DesignLimitation]
    ethical_considerations: list[str] = Field(description="Relevant ethical issues for this design")
    irb_plan: IRBPlan | None = None
    reporting_standard: str = Field(
        description="Recommended EQUATOR guideline (PRISMA / CONSORT / STROBE / COREQ / SQUIRE / Other)"
    )
    preregistration: Preregistration


class ClaimVerification(BaseModel):
    """Single claim verification result from cross-model check."""

    model_config = ConfigDict(frozen=True)

    claim: str = Field(description="The claim being verified")
    verdict: str = Field(description="VERIFIED, SUSPICIOUS, or UNVERIFIABLE")
    reasoning: str = Field(description="Explanation of the verdict")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the verdict")


class IndependentVerificationReport(BaseModel):
    """Output from independent verification of research claims."""

    model_config = ConfigDict(frozen=True)

    claims: list[ClaimVerification] = Field(default_factory=list)
    overall_assessment: str = Field(description="Brief summary of verification findings")
    red_flags: list[str] = Field(default_factory=list, description="Specific concerns found")
