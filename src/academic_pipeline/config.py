"""Pipeline configuration with type-safe environment variable loading.

Uses pydantic-settings: reads from env vars automatically, validates types,
supports .env files natively. No manual os.environ.get() or load_dotenv().
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from academic_pipeline.core.enums import AgentType


logger = logging.getLogger(__name__)

# config.py is at <root>/src/academic_pipeline/config.py — three .parent hops
# land at the project root which contains skills/, configs/, examples/, etc.
PROJECT_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIRS = [str(PROJECT_ROOT / "skills")]


class PipelineConfig(BaseSettings):
    """Type-safe, validated pipeline configuration.

    Reads from environment variables automatically (case-insensitive). Falls back to .env file if present. All
    validation happens at construction.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        yaml_file=("configs/default.yaml", "configs/dev.yaml"),
        yaml_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Define settings source precedence.

        Precedence (highest -> lowest):
        1. init kwargs (PipelineConfig(foo=1))
        2. env vars
        3. .env file
        4. configs/dev.yaml (overrides) — YamlConfigSettingsSource reads tuple in
           order, later files override earlier, so dev wins over default.
        5. configs/default.yaml
        6. file secrets
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    # API keys (exported to os.environ for external SDKs)
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str = ""
    anthropic_max_retries: int = Field(default=3, ge=0)
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = ""
    exa_api_key: SecretStr = SecretStr("")
    s2_api_key: SecretStr = SecretStr("")

    # Model selection — single source of truth (see runtime.model_registry).
    default_model: str = "openai:deepseek-v4-pro"
    """Provider-prefixed model every agent runs on unless overridden. Flip the
    whole pipeline between providers by setting DEFAULT_MODEL in .env, e.g.
    `openai:deepseek-v4-pro` -> `anthropic:claude-opus-4-8`. The 53 agent specs
    carry no model literal — `runtime.model_registry.build_agent` injects this."""
    model_overrides: dict[str, str] = Field(default_factory=dict)
    """Per-agent model overrides keyed by agent registry name — the escape hatch
    for cross-model verification or cost lanes. Example (JSON in .env):
    `MODEL_OVERRIDES={"independent_verifier":"anthropic:claude-opus-4-8"}`. Any
    agent absent from this map uses `default_model`."""

    # Temperatures
    temperature_research: float = Field(default=0.3, ge=0.0, le=1.0)
    temperature_writing: float = Field(default=0.5, ge=0.0, le=1.0)
    temperature_review: float = Field(default=0.3, ge=0.0, le=1.0)

    # Quality
    effort: Literal["max", "high", "medium", "low"] = "max"

    # Checkpointing
    checkpointer_backend: Literal["memory", "sqlite", "postgres"] = "sqlite"
    database_url: str = ""
    sqlite_path: str = str(Path.home() / ".academic_pipeline" / "checkpoints.db")

    # Loop limits
    max_integrity_fix_loops: int = Field(default=3, ge=1)
    # Per-node evaluator-optimizer
    evaluator_models: list[str] = Field(
        default=["openai:deepseek-v4-pro"],
    )
    max_node_iterations: int = Field(default=2, ge=1)
    node_quality_threshold: float = Field(default=7.0, ge=0.0, le=10.0)
    node_quality_thresholds: dict[str, float] = Field(default_factory=dict)
    """Per-node override map. Keys are node names (e.g. "draft_writer", "synthesis").
    Missing entries fall back to `node_quality_threshold`. Values must be in [0.0, 10.0].
    PRD §6.12.T5 + §6.11.T4."""
    enable_node_evaluation: bool = True
    enable_compliance_check: bool = True

    # Traceability layer (SCI port — see docs/superpowers/specs/2026-05-03-sci-traceability-port-design.md)
    traceability_mode: Literal["off", "partial", "full"] = "off"
    """SCI-traceability layer enable: off (default), partial (validator+notes), full (+dialogue+code-appendix)."""
    # Chain-of-Ideas KG (SCI port Spec 2 — see docs/superpowers/specs/2026-05-03-chain-of-ideas-kg-design.md)
    chain_of_ideas_enabled: bool = True
    """When true, run the Chain-of-Ideas extractor + thesis extractor as the canonical
    research path. PRD §6.1.T1 Phase 4 flipped this default from False → True; the
    legacy KnowledgeGraphNode now runs only under `legacy_knowledge_graph=true`
    (PRD §6.1.T2 Phase 4 graph-topology rewiring)."""
    copilot_enabled: bool = False
    """When true, run interactive copilot checkpoints at 3 named pipeline boundaries."""
    max_dialogue_turns: int = 3
    """Maximum writer↔reviewer dialogue turns before forcing termination (full mode only)."""

    # Novelty gate (SCI Spec 3 Phase 1 — hard-reject only)
    novelty_gate_enabled: bool = False
    """When true, run Semantic Scholar novelty gate between intake and research."""
    novelty_gate_tau_warn: float = Field(default=0.78, ge=0.0, le=1.0)
    """Below this max title similarity → NOVEL verdict."""
    novelty_gate_tau_block: float = Field(default=0.92, ge=0.0, le=1.0)
    """At/above this max title similarity → REDUNDANT (hard reject)."""
    novelty_gate_top_n: int = Field(default=10, ge=1)
    """Number of S2 candidates to retain in the result."""

    # Point-wise novelty reviewer (SCI Spec 4 Phase 1 — report only)
    pointwise_novelty_enabled: bool = False
    """When true, run the point-wise novelty reviewer in the review subgraph
    after parallel reviewers and before editorial synthesis."""
    pointwise_novelty_top_n_per_claim: int = Field(default=5, ge=1)
    """Number of S2 candidates to retrieve per extracted contribution claim."""

    # Persona-anchored reviewer panel (SCI Spec 5 Phase 1 — additive, behind flag)
    persona_reviewers_enabled: bool = False
    """When true, ParallelReviewerNode dispatches the 3 persona-anchored
    reviewers (senior_gatekeeper, applied_practitioner, methodology_purist)
    instead of the default 3 reviewers. Default off preserves current
    behavior."""
    target_journal: str = "Journal of Biomedical Informatics"
    """Human-readable journal name used by persona reviewers in their prompts."""
    target_acceptance_rate: float = Field(default=0.20, ge=0.0, le=1.0)
    """0.20 = persona reviewers behave as if rejecting 80% of submissions."""

    # Cascaded reviewer pipeline (SCI Spec 6 Phase 1 — composes Specs 1+4+5)
    cascaded_review_enabled: bool = False
    """When true, run CascadedReviewNode after PointWiseNoveltyReviewerNode and
    before EditorialSynthesizerNode. Phase 1 populates state.cascade_result;
    editorial reads but does not yet enforce the cascade verdict (Phase 2)."""
    cascade_short_circuit_on_stage_a: bool = True
    """Stage A (numerical grounding) is a hard gate when this is true."""
    cascade_short_circuit_on_stage_b: bool = True
    """Stage B (novelty) is a hard gate when this is true."""
    cascade_short_circuit_on_stage_c: bool = False
    """Stage C (methodology) gates when true. Default false — methodology can
    be salvaged with revision rather than outright rejection."""

    # Checklist ethics (SCI Spec 8 Phase 1 — additive, behind flag)
    ethics_checklist_enabled: bool = True
    """When true, run the 12-item PRISMA-trAIce `EthicsChecklistNode` in the
    integrity subgraph in place of the legacy freeform ethics review.
    PRD §6.5.T1 Phase 4 flipped this default `False → True` once the node
    landed in `integrity/graph.py`. Pairs with §6.1.T6 which deletes the
    legacy research-side `EthicsReviewNode`."""

    # SCI escape hatches — when True, force the legacy/pre-SCI behavior even if
    # the corresponding canonical flag is enabled. Provided per PRD §6.12.T1 so
    # operators can revert any single subsystem if a Phase 2 wiring regresses.
    legacy_traceability: bool = False
    """When true, bypass traceability layer (validator + dialogue + code appendix)."""
    legacy_chain_of_ideas: bool = False
    """When true, bypass Chain-of-Ideas extractor + thesis extractor; use legacy KG only."""
    legacy_knowledge_graph: bool = False
    """PRD §6.1.T1 — when true, the legacy `KnowledgeGraphNode` runs alongside (or
    instead of) the canonical `ChainOfIdeasNode`. Default False keeps Phase 4
    behavior (CoI canonical, KG retired). PRD §6.1.T2 rewires `research/graph.py`
    to honor this flag in the Phase 4 topology rewrite."""
    legacy_novelty_gate: bool = False
    """When true, skip Semantic Scholar novelty gate even if enabled."""
    legacy_pointwise_novelty: bool = False
    """When true, skip point-wise novelty reviewer even if enabled."""
    legacy_persona_reviewers: bool = False
    """When true, ParallelReviewerNode falls back to default reviewers, not personas."""
    legacy_cascaded_review: bool = False
    """When true, EditorialSynthesizerNode ignores cascade_result; legacy synthesis only."""
    legacy_exploration_breadth: bool = False
    """When true, single-design pathway only — bypass N-design bundling/scoring."""
    legacy_ethics_checklist: bool = False
    """When true, force legacy freeform ethics review even if checklist node enabled."""

    # Network
    ssl_verify: bool = True
    http_timeout_seconds: int = Field(default=20, ge=1)
    http_max_retries: int = Field(default=3, ge=0)
    http_backoff_base: float = Field(default=1.0, ge=0.1)

    # Resume limits
    max_pipeline_resumes: int = Field(default=50, ge=1)
    max_subgraph_resumes: int = Field(default=20, ge=1)

    # LLM resilience
    llm_timeout_seconds: int = Field(default=600, ge=10)
    llm_max_retries: int = Field(default=3, ge=1)

    # Logging
    log_dir: str = Field(default="logs")
    log_max_bytes: int = Field(default=10_485_760, ge=1)  # 10 MB
    log_backup_count: int = Field(default=5, ge=0)

    # Context compaction
    compaction_token_threshold: int = Field(default=800_000, ge=1)

    # Experiment subgraph
    experiment_timeout_seconds: int = Field(default=1800, ge=10)
    experiment_max_retries: int = Field(default=3, ge=1)
    experiment_max_improvements: int = Field(default=2, ge=0)
    experiment_seeds: list[int] = Field(default=[42, 123, 456])
    experiment_enabled: bool = True
    force_experiment: bool = False
    experiment_allowed_packages: list[str] = Field(
        default=[
            "pandas",
            "numpy",
            "sklearn",
            "scikit-learn",
            "xgboost",
            "lightgbm",
            "matplotlib",
            "seaborn",
            "scipy",
            "statsmodels",
            "ucimlrepo",
            "datasets",
            "requests",
            "catboost",
            "shap",
            "scikit-posthocs",
            "autogluon",
            "gluonts",
            "statsforecast",
            "chronos",
            "transformers",
            "timm",
            "mmdet",
            "mmcv",
        ],
    )

    # Bypass the CrossRef DOI verification gate in BibTexGenerator. Default
    # is fail-closed (REN001 aborts the pipeline on any unverified DOI). Set
    # True when CrossRef is rate-limiting or you trust the agent's DOIs.
    allow_unverified_dois: bool = False

    # Dataset discovery + email alerts (values from .env)
    experiment_dataset_path: str = ""
    experiment_alert_email: str = ""
    experiment_alert_sender: str = ""
    experiment_smtp_server: str = ""
    experiment_smtp_port: int = 25

    # Exploration breadth (Spec 7) — bundle of N designs, score, run top K.
    # Phase 1: scoring/selection only; only the single highest-scoring design
    # is actually run (no fan-out yet). Phase 2 will parallelize K runs.
    exploration_breadth_enabled: bool = False
    n_design_alternatives: int = Field(default=4, ge=2, le=10)
    k_designs_to_run: int = Field(default=2, ge=1, le=5)

    # Docker execution
    experiment_use_docker: bool = True
    experiment_docker_image: str = "academic-pipeline-sandbox:latest"
    experiment_docker_memory: str = "4g"
    experiment_docker_cpus: str = "2"
    experiment_docker_pass_api_keys: bool = False

    # Rate limiting
    tool_call_delay_seconds: int = Field(default=10, ge=0)

    @field_validator("default_model")
    @classmethod
    def default_model_not_empty(cls, v: str) -> str:
        """Validate that default_model is not empty."""
        if not v.strip():
            raise ValueError("default_model cannot be empty")
        return v

    @field_validator("node_quality_thresholds")
    @classmethod
    def node_quality_thresholds_in_range(cls, v: dict[str, float]) -> dict[str, float]:
        """Each per-node threshold must be in [0.0, 10.0] (matches global field bounds)."""
        for node_name, threshold in v.items():
            if not 0.0 <= threshold <= 10.0:
                raise ValueError(f"node_quality_thresholds[{node_name!r}]={threshold} out of range [0.0, 10.0]")
        return v

    @model_validator(mode="after")
    def postgres_requires_database_url(self) -> PipelineConfig:
        """Validate that postgres backend has a database_url."""
        if self.checkpointer_backend == "postgres" and not self.database_url:
            raise ValueError("database_url is required when checkpointer_backend is 'postgres'")
        return self

    @model_validator(mode="after")
    def export_sdk_env_vars(self) -> PipelineConfig:
        """Export API keys and URLs to os.environ for external SDKs.

        Anthropic, OpenAI, and Exa SDKs read credentials from os.environ directly.
        PydanticSettings reads .env into config fields but does not populate os.environ.
        This bridges the gap — single source of truth in .env, no load_dotenv() needed.
        """
        import os

        sdk_exports: list[tuple[str, str]] = [
            ("ANTHROPIC_API_KEY", self.anthropic_api_key.get_secret_value()),
            ("ANTHROPIC_BASE_URL", self.anthropic_base_url),
            ("ANTHROPIC_MAX_RETRIES", str(self.anthropic_max_retries)),
            ("OPENAI_API_KEY", self.openai_api_key.get_secret_value()),
            ("OPENAI_BASE_URL", self.openai_base_url),
            ("EXA_API_KEY", self.exa_api_key.get_secret_value()),
            ("ANTHROPIC_TIMEOUT", str(self.llm_timeout_seconds)),
        ]
        for env_var, value in sdk_exports:
            if value:
                os.environ.setdefault(env_var, value)
        return self

    _TEMP_MAP: ClassVar[dict[AgentType, str]] = {
        AgentType.RESEARCH: "temperature_research",
        AgentType.INTEGRITY: "temperature_research",
        AgentType.REVIEW: "temperature_review",
        AgentType.WRITING: "temperature_writing",
    }

    def get_temperature(self, agent_type: AgentType | str) -> float:
        """Return the temperature setting for the given agent type.

        Args:
            agent_type: Agent role — accepts AgentType enum or raw string.

        Returns:
            The configured temperature float for the agent type.

        Raises:
            ValueError: If agent_type is not a recognized AgentType value.
        """
        field_name = self._TEMP_MAP.get(AgentType(agent_type))
        if field_name is None:
            raise ValueError(f"Unknown agent_type: {agent_type!r}")
        return getattr(self, field_name)

    def get_node_threshold(self, node_name: str) -> float:
        """Return the quality threshold for a node, falling back to the global default.

        Per PRD §6.12.T5 + §6.11.T4: missing entries in `node_quality_thresholds`
        fall back to the global `node_quality_threshold` field. Use this helper
        from evaluator code instead of reading the dict directly so the fallback
        is consistent.
        """
        return self.node_quality_thresholds.get(node_name, self.node_quality_threshold)


def get_config() -> PipelineConfig:
    """Return the default PipelineConfig (constructed on first call, cached)."""
    return PipelineConfig()


DEFAULT_CONFIG = get_config()
