# Architecture

## Overview

The academic pipeline is a four-phase system built on PydanticAI agents and
pydantic-graph. A pipeline orchestrator graph drives four subgraphs in sequence:
Research, Writing, Review, and Integrity. Each subgraph has its own state
dataclass, agent pool (YAML specs loaded via `Agent.from_file`), and internal
revision loops. All agents share a single dependency container (`PipelineDeps`)
that provides configuration, rate limiting, and HITL checkpoints.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Pipeline Orchestrator                              │
│                      (pipeline/nodes.py — 14 nodes)                     │
│                                                                         │
│  IntakeNode                                                             │
│      │                                                                  │
│      ▼                                                                  │
│  NoveltyGateNode             (Spec 3 Phase 1 — flag-gated)              │
│      │                       Hard-rejects topics with S2 title          │
│      │                       similarity ≥ tau_block (0.92 default)      │
│      ▼                                                                  │
│  ResearchPhaseNode ──→ build_research_graph() ──→ merge results         │
│      │                                                                  │
│      ▼                                                                  │
│  ExperimentClassifierNode    Decides if topic warrants experiments      │
│      │                                                                  │
│      ├── needs_experiments ──→ ExperimentPhaseNode                      │
│      │                              ├── success ──→ WritePhaseNode      │
│      │                              ├── failure + retries ──→           │
│      │                              │      (orchestrator-level fix loop)│
│      │                              └── max retries ──→ AbortNode → End │
│      │                                                                  │
│      └── no experiments ────────────────────→ WritePhaseNode            │
│                                                     │                   │
│                                                     ▼                   │
│  PreIntegrityNode ◄──► IntegrityFixNode (loop, max=cfg)                 │
│      │                                                                  │
│      ▼                                                                  │
│  ReviewPhaseNode ──→ build_review_graph() ──→ merge results             │
│      │                                                                  │
│      ▼                                                                  │
│  FinalIntegrityNode ◄──► FinalIntegrityFixNode (loop, max=cfg)          │
│      │                                                                  │
│      ▼                                                                  │
│  FinalizeNode → SummaryNode → End                                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

Each orchestrator node builds a subgraph state, runs the subgraph to
completion, then merges outputs back into `PipelineState`.

---

## Shared Infrastructure

### Dependencies (`core/deps.py`)

```
PipelineDeps
├── config: PipelineConfig      # pydantic-settings from env/YAML
├── hitl_handler                 # human-in-the-loop callback (auto-continue default)
└── throttle()                   # async sleep between agent calls (rate limit)
```

### Enums (`core/enums.py`)

| Enum                | Purpose                                                                        |
| ------------------- | ------------------------------------------------------------------------------ |
| `Stage`             | Pipeline phases: research → summary                                            |
| `PipelineStatus`    | Lifecycle: initializing → completed/aborted                                    |
| `StageStatus`       | Per-stage status: pending / in_progress / completed / blocked                  |
| `CheckpointType`    | Checkpoint granularity: FULL / SLIM / MANDATORY                                |
| `AgentType`         | Agent role identifiers: research / writing / review / integrity                |
| `Verdict`           | Quality gates: PASS / PASS_WITH_CONDITIONS / REVISE / FAIL / BLOCKED / CLEARED |
| `EditorialDecision` | Editor output: Accept → Reject                                                 |
| `ReviewDimension`   | Scored dimensions: originality → writing (used in revision routing)            |
| `IssueSeverity`     | Issue severity: critical → suggestion (used in revision routing)               |
| `RevisionSource`    | Who requested revision: editor / DA1 / DA2 (used in revision routing)          |

### Context Builder (`runtime/context.py`)

`build_context(state, keys, node_name=None)` concatenates state fields into
a prompt string for agents. Each key is looked up as an attribute on the
state dataclass; dicts extract `"raw"`, lists are joined, everything else
is stringified.

When `node_name` is provided and `state.revision_context` exists with a
matching `target_node`, a `REVISION INSTRUCTIONS` block is appended
containing the issues list, previous output, and feedback summary. After
consumption, `revision_context` is cleared to `None` (single point of
responsibility — no node can forget to clear it).

### Agent Loading

All agents are defined as YAML specs in `agents/<phase>/`. Each subgraph
module loads them at import time via `Agent.from_file()`:

```python
_agents: dict[str, Agent[PipelineDeps, Any]] = {
    "research_question": Agent.from_file("agents/research/research_question.yaml", ...),
    "editor_in_chief": Agent.from_file(..., output_type=EditorReview),  # structured output
    "devils_advocate": Agent.from_file(..., output_type=DAReport),      # structured output
    ...
}
```

Most agents return `str`. The editor-in-chief returns `EditorReview` and the
devil's advocate returns `DAReport` (Pydantic models with typed fields).
Tools (search, DOI verification, citation formatting, etc.) are attached
to specific agents at load time.

---

## Phase 1: Research Subgraph

**File:** `research/graph.py`
**State:** `ResearchState`
**Nodes (12):** ResearchQuestion, ResearchArchitect, Bibliography, SourceVerification, KnowledgeGraph, Synthesis, ChainOfIdeas, ReportCompiler, CrossModelVerification, EditorInChief, EthicsReview, MergeReviews
**Specs (15):** research_question, research_architect, bibliography, source_verification, knowledge_graph, synthesis, chain_of_ideas_extractor, thesis_extractor, report_compiler, independent_verifier, editor_in_chief, ethics_review, plus 3 currently unwired (meta_analysis, monitoring, risk_of_bias) staged for future Phase-2 wirings

```
ResearchQuestionNode
       │
       ▼
ResearchArchitectNode
       │
       ▼
BibliographyNode
       │
       ▼
SourceVerificationNode      Verify DOIs, retractions
       │
       ▼
KnowledgeGraphNode          Concept/entity graph
       │
       ▼
SynthesisNode
       │
       ▼
ChainOfIdeasNode            (Spec 2 Phase 1 — flag-gated)
       │                    Extracts development chain + thesis_extractor
       ▼                    runs alongside; populates state.chain + state.thesis
ReportCompilerNode
       │
       ▼
CrossModelVerificationNode  Independent second-pass review of claims/citations
       │                    (Opus 4.7, anthropic_effort: max)
       ▼
EditorInChiefNode           → EditorReview (structured output)
       │
       ▼
EthicsReviewNode            12-item PRISMA-trAIce checklist (Spec 8)
       │                    → EthicsChecklist (structured output)
       │
       ├── BLOCKED ─────→ End("BLOCKED: Ethics review blocked delivery.")
       └── otherwise ──→ MergeReviewsNode
                              │
                              ▼
                            End
```

The research subgraph is now strictly **linear forward**. The DA checkpoints,
DA1/DA2 loops, MergeReviews→back-routing, and HITL UserConfirm have all been
removed (Loop Fix work, mid-2026). Quality is enforced by per-node evaluator
panels (`runtime/evaluator.py`) inside each node — `traced_agent_run()` invokes
the agent up to `max_node_iterations` times until the evaluator passes.
MergeReviewsNode is now a terminal aggregator, not a routing node.

### Per-node evaluator gate

Each research node wraps its `agent.run()` in `run_with_evaluation()`, which:

1. Runs the agent with `traced_agent_run()`.
2. Sends the output to a 3-model evaluator panel (Opus 4.7 only post-2.4 — the
   GPT/Gemini panel members were retired when the API surface diverged).
3. If the evaluator returns NEEDS_IMPROVEMENT and `iteration < max_node_iterations`,
   re-runs with the evaluator feedback appended to the prompt.
4. After max iterations, accepts the latest output regardless.

Quality knobs in `default.yaml`:

| Knob | Default | Effect |
|------|---------|--------|
| `enable_node_evaluation` | true | Master switch for the per-node panel |
| `node_quality_threshold` | 7.0 | Minimum dimension score for PASS |
| `max_node_iterations` | 3 | Cap on retry-with-feedback rounds |

---

## Phase 2: Writing Subgraph

**File:** `writing/graph.py`
**State:** `WritingState`
**Nodes (16):** Intake, LiteratureStrategist, StructureArchitect, ArgumentBuilder, SectionPlanner, ParallelSectionDraft, SectionMerger, DraftWriter, CitationCompliance, ParallelAbstractViz, MergePhase5, FigureVerification, PeerReviewer, Formatter, BibTexGenerator, LatexCompiler
**Specs (13):** intake, literature_strategist, structure_architect, argument_builder, section_writer, draft_writer, citation_compliance, abstract, visualization, figure_verifier, peer_reviewer, formatter, revision_coach

```
IntakeNode                       Analyze topic; route by bibliography presence
       │
       ├── has bibliography ──→ LiteratureStrategistNode
       │                              │
       └── no bibliography ───────────┤
                                      ▼
                           StructureArchitectNode    Design paper outline
                                      │
                                      ▼
                            ArgumentBuilderNode      Build argument blueprint
                                      │
                                      ▼
                            SectionPlannerNode       Decompose paper into sections
                                      │
                                      ▼
                       ParallelSectionDraftNode      asyncio.gather over sections
                           ┌──────────┴──────────┐   (per-section section_writer agent)
                              SectionMergerNode      Stitch sections into draft
                                      │              + receiver-side traceability
                                      ▼              validators (Spec 1)
                             DraftWriterNode         Coherence pass over merged draft
                                      │
                                      ▼
                          CitationComplianceNode     Audit citation formatting
                                      │
                                      ▼
                         ParallelAbstractVizNode     asyncio.gather:
                           ┌──────────┴──────────┐    AbstractNode + VisualizationNode
                                      ▼
                            MergePhase5Node           Merge abstract + figures into draft
                                      │
                                      ▼
                          FigureVerificationNode     VLM figure_verifier (Opus 4.7 max)
                                      │
                                      ▼
                            PeerReviewerNode ◄────────────┐
                                      │                   │
                              ┌───────┼───────┐           │
                           ACCEPT   MAJOR   max rounds    │
                           MINOR   REVISION  exceeded     │
                              │       │        │         │
                              │       └────────┼─────────┘
                              ▼                ▼  (revision loop wraps draft writer)
                         FormatterNode
                              │
                              ▼
                       BibTexGeneratorNode (when LaTeX requested)
                              │
                              ▼
                       LatexCompilerNode             pandoc + tectonic → PDF
                              │                     + apply_traceability_substitutions
                              ▼                       (Spec 1: token → \hyperlink + appendices)
                            End
```

**Score trajectory tracking:** PeerReviewerNode tracks scores across revision
rounds, detects regressions, and supports early-stop when scores converge
with no critical issues.

**Output formats:** Markdown is the default. When `latex_compilation_enabled`
is on, BibTexGeneratorNode + LatexCompilerNode run after FormatterNode to
emit a tectonic-compiled PDF with full traceability hyperlinks.

---

## Phase 3: Review Subgraph

**File:** `review/graph.py`
**State:** `ReviewState`
**Nodes (6):** FieldAnalyst, ParallelReviewer, PointWiseNoveltyReviewer, CascadedReview, EditorialSynthesizer, RevisionCoaching
**Specs (12):** field_analyst, eic, methodology_reviewer, domain_reviewer, perspective_reviewer, methodology_purist_reviewer, applied_practitioner_reviewer, senior_gatekeeper_reviewer, claim_extractor, claim_novelty_assessor, numerical_claims_auditor, editorial_synthesizer

```
FieldAnalystNode                 Analyze paper's field
       │
       ▼
ParallelReviewerNode             asyncio.gather across reviewer panel
       │                         When persona_reviewers_enabled (Spec 5):
       │                           methodology_purist + applied_practitioner +
       │                           senior_gatekeeper personas
       │                         Otherwise: methodology + domain + perspective
       │
       ├── pointwise_novelty_enabled (Spec 4) ──→ PointWiseNoveltyReviewerNode
       │                                          (claim_extractor + S2 retrieval +
       │                                           claim_novelty_assessor → NoveltyReport)
       │                                                     │
       ├── cascaded_review_enabled (Spec 6) ──→ CascadedReviewNode
       │                                        (4 stages: numerical → novelty →
       │                                         methodology → narrative;
       │                                         short-circuit on REJECT)
       │                                                     │
       ▼                                                     ▼
                          EditorialSynthesizerNode    Compose verdict from
                                                      reviewer panel + (optional)
                                                      novelty + cascade outputs
                                       │
                               ┌───────┼───────┐
                            ACCEPT    REVISION  REJECT
                               │       │        │
                              End  RevisionCoachingNode → End
                                       │
                                      End
```

**Reviewer composition:** `ParallelReviewerNode` runs three reviewers
concurrently. The persona slate (Spec 5) and the alternate cascade pipeline
(Spec 6) are switched on via config flags; without flags, the legacy
methodology/domain/perspective trio runs and feeds straight into
EditorialSynthesizer.

**No backward routing:** The review subgraph is read-only on the paper draft
and terminates at End. Revision happens externally (orchestrator can re-enter
WritePhaseNode based on the editorial decision).

---

## Phase 4: Integrity Subgraph

**File:** `integrity/graph.py`
**State:** `IntegrityState`
**Nodes (1):** IntegrityCheck
**Specs (2):** integrity_verification, compliance_check

Single-node subgraph. Returns a verdict (PASS / PASS_WITH_CONDITIONS / FAIL).
The orchestrator handles fix loops externally via
`PreIntegrityNode ↔ IntegrityFixNode` and
`FinalIntegrityNode ↔ FinalIntegrityFixNode`.

The `integrity_verification` agent has three tools attached:
`extract_claims`, `check_plagiarism_heuristic`, `detect_ai_style_indicators`.

---

## Phase 5: Experiment Subgraph

**File:** `experiment/graph.py`
**State:** `ExperimentState`
**Nodes (7):** ExperimentDesign, ExperimentDesignBundle, DesignSelection, DesignComparison, InteractiveML, Judge, Analysis
**Specs (10):** experiment_classifier, experiment_designer, experiment_designer_bundle, design_scorer, design_comparator, ml_engineer, experiment_judge, experiment_improver, result_analyzer, figure_reviewer

Runs only when `ExperimentClassifierNode` (in the orchestrator) decides the
topic warrants computational experiments and a HuggingFace dataset is
available.

```
ExperimentDesignNode                 (default path)
       │
       ├── exploration_breadth_enabled (Spec 7 Phase 1): ─┐
       │                                                  ▼
       │                              ExperimentDesignBundleNode  N=4 alternatives
       │                                                  │
       │                                                  ▼
       │                              DesignSelectionNode     score → pick top K=2
       │                                                  │   (Phase 1: only top-1
       │                                                  │   actually executes)
       ▼                                                  ▼
                              InteractiveMLNode ◄────────────────┐
                              (ml_engineer agent + persistent     │
                               Docker sandbox; AgentMessageCache  │
                               persists conversation across       │
                               judge loops + crash recovery)      │
                                       │                          │
                                       ▼                          │
                                  JudgeNode                       │
                                  (experiment_judge: PASS,        │
                                   IMPROVE, FAIL — IMPROVE        │
                                   triggers experiment_improver)  │
                                       │                          │
                              ┌────────┼────────┐                 │
                            PASS     IMPROVE   FAIL               │
                              │        │        │                 │
                              │        └────────┘─────────────────┘
                              ▼              (max 2 iterations)
                          AnalysisNode                  result_analyzer
                              │                         + figure_reviewer (VLM)
                              │
                              ├── exploration_breadth_enabled ──→ DesignComparisonNode
                              │                                   (when applicable)
                              ▼
                            End
```

**Sandboxing:** `tools/execution/` provides AST safety scanning
(`validate_script`), Docker container lifecycle (`DockerEnv`), and
post-execution sanity checks (`sanity_check_results`,
`verify_plan_alignment`, `verify_dataset_urls`). HuggingFace is the only
permitted dataset source; sklearn/UCI/Kaggle are rejected by
`experiment_classifier` and `experiment_designer`.

**ML stack:** AutoGluon — `TabularPredictor`, `TimeSeriesPredictor`,
`MultiModalPredictor`. Predictor type is chosen by `experiment_classifier`
(`tabular` / `timeseries` / `multimodal`).

**Failure handling:** If experiments fail and retries remain, the orchestrator
routes to `ExperimentFixNode` (replaces the design via `experiment_improver`)
and re-enters `ExperimentPhaseNode`. After max retries, `AbortNode` ends the
pipeline cleanly.

---

## Pipeline Orchestrator Loops

The orchestrator (`pipeline/nodes.py` (under `src/academic_pipeline/`)) manages three revision loops that
wrap the subgraphs:

### Integrity Fix Loop

```
PreIntegrityNode
       │
       ├── PASS ──→ ReviewPhaseNode
       │
       └── FAIL ──→ IntegrityFixNode ──→ PreIntegrityNode (loop)
                    (max: config.max_integrity_fix_loops)
```

Same pattern repeats for `FinalIntegrityNode ↔ FinalIntegrityFixNode`.

### Review → Revise Loop

```
ReviewPhaseNode (read-only)
       │
       └──→ FinalIntegrityNode
```

Review is read-only.  The writing subgraph handles per-node evaluation
internally, so no global revision loop is needed.

---

## Data Flow

State flows through the pipeline as a chain of merges:

```
PipelineState
    │
    ├──→ ResearchState (built from topic)
    │         │
    │         └──→ merged back: rq_brief, methodology_blueprint,
    │              bibliography, synthesis
    │
    ├──→ WritingState (built from research outputs)
    │         │
    │         └──→ merged back: paper_draft, paper_config, paper_outline,
    │              argument_blueprint, figure_package, style_profile,
    │              score_history, score_trajectory_flags
    │
    ├──→ IntegrityState (built from paper_draft)
    │         │
    │         └──→ merged back: integrity_report
    │
    └──→ ReviewState (built from paper_draft + review artifacts)
              │
              └──→ merged back: review_report, revision_roadmap,
                   response_to_reviewers, editorial_decision
```

---

## Tools

Tools are plain async functions attached to specific agents at load time. Capability-grouped sub-packages under `src/academic_pipeline/tools/`.

### Bibliography (`tools/bibliography/`)

| Tool | Agent | Source |
|------|-------|--------|
| `web_search_exa` | bibliography, experiment_designer, claim_novelty_assessor | Exa direct API (no MCP) |
| `web_fetch_exa` | bibliography, experiment_designer | Exa direct API |
| `find_similar_papers` | bibliography | Exa similarity search |
| `verify_doi` | source_verification | DOI resolution + CrossRef |
| `check_retraction` | source_verification | Retraction Watch |
| `resolve_doi_metadata` | source_verification | CrossRef metadata |
| `search_s2_by_title` | source_verification, novelty_gate, claim_novelty_assessor | Semantic Scholar |
| `batch_verify_s2` | source_verification | Semantic Scholar batch |
| `get_s2_paper_details` | source_verification | Semantic Scholar detail |
| `format_citation` | citation_compliance | Citation formatting (APA7/Chicago/MLA/IEEE/Vancouver) |
| `validate_citation` | citation_compliance | Citation validation |
| `convert_citation_style` | citation_compliance | Style conversion |
| `bibtex_for_source` | bibtex_generator (non-agent) | BibTeX entry generation |

### Execution (`tools/execution/`)

| Tool | Agent | Purpose |
|------|-------|---------|
| `validate_script` | (called pre-exec by InteractiveMLNode) | AST safety scan — rejects unsafe imports/calls |
| `execute_script` | ml_engineer (via Docker container tools) | Run code in persistent Docker sandbox + collect artifacts |
| `sanity_check_results` | result_analyzer | Catch impossible metrics (>1.0 accuracy, etc.) |
| `verify_plan_alignment` | result_analyzer | Confirm executed code matches design |
| `verify_dataset_urls` | experiment_designer | Confirm HuggingFace dataset path resolves |
| `send_dataset_alert` | experiment_designer | SMTP alert when no dataset can be found |
| AutoGluon templates | ml_engineer (referenced in prompt) | Tabular / timeseries / multimodal scaffolds |

### Rendering (`tools/rendering/`)

| Tool | Agent | Purpose |
|------|-------|---------|
| `figure_executor.execute_figure_script` | VisualizationNode | Run figure scripts in sandbox |
| `latex_compiler.compile_pdf` | LatexCompilerNode | Pandoc + tectonic PDF compilation with traceability hyperlinks |

### Integrity (`tools/integrity_tools.py`)

| Tool | Agent | Purpose |
|------|-------|---------|
| `extract_claims` | integrity_verification | Extract factual claims from prose |
| `check_plagiarism_heuristic` | integrity_verification | n-gram overlap detection |
| `detect_ai_style_indicators` | integrity_verification | Stylometric AI-writing flags |

### Other utilities

| Module | Purpose |
|--------|---------|
| `tools/agent_cache.py` | `AgentMessageCache` — persists `ModelMessagesTypeAdapter` messages to disk so InteractiveMLNode can resume mid-conversation across judge loops or crash recovery |

---

## File Layout

```
src/academic_pipeline/
├── __init__.py                 Public API exports (Pipeline, PipelineConfig, PipelineResult, DEFAULT_CONFIG)
├── __main__.py                 `python -m academic_pipeline ...` entry
├── cli.py                      Typer CLI entry point (run / supervised-run / watchdog / dashboard)
├── config.py                   PipelineConfig (pydantic-settings) + YamlConfigSettingsSource
├── observability.py            Logfire + truststore setup + keepalive provider patch
├── persistence.py              FileStatePersistence (resume support)
├── logging_config.py           Logging setup
├── py.typed                    PEP 561 marker
├── sdk/
│   ├── pipeline.py             Pipeline class (public async API)
│   └── result.py               PipelineResult with .save()
├── pipeline/
│   ├── graph.py                build_pipeline_graph()
│   ├── nodes.py                13 orchestrator nodes
│   └── state.py                PipelineState dataclass
├── research/
│   ├── agents.py               Agent registry (Agent.from_file)
│   ├── graph.py                research nodes + build_research_graph()
│   ├── state.py                ResearchState dataclass
│   └── specs/                  13 YAML agent specs (co-located with code)
├── writing/
│   ├── agents.py               Agent registry
│   ├── graph.py                13 writing nodes + build_writing_graph()
│   ├── state.py                WritingState dataclass
│   └── specs/                  13 YAML agent specs
├── review/
│   ├── agents.py               Agent registry
│   ├── graph.py                5 review nodes + build_review_graph()
│   ├── state.py                ReviewState dataclass
│   └── specs/                  6 YAML agent specs (post-2.4 dead-code purge)
├── integrity/
│   ├── agents.py               Agent registry
│   ├── graph.py                1 integrity node + build_integrity_graph()
│   ├── state.py                IntegrityState dataclass
│   └── specs/                  2 YAML agent specs
├── experiment/
│   ├── agents.py               Interactive ML + judge agents
│   ├── graph.py                4-node experiment subgraph
│   ├── state.py                ExperimentState dataclass
│   ├── references/             Tabular / timeseries / multimodal templates
│   └── specs/                  7 YAML agent specs
├── recovery/                   4-layer hang-recovery system (added in v2.3)
│   ├── transport.py            keepalive httpx.AsyncClient factory
│   ├── bounded_run.py          AgentTimeoutError + bounded_agent_run wrapper
│   ├── process_state.py        ProcessLock context manager (PID + PGID files)
│   ├── heartbeat.py            Heartbeat context manager (daemon thread)
│   ├── watchdog.py             WatchdogConfig + run_watchdog (3-strikes escalation)
│   └── supervisor.py           Tier-3 supervised_run launcher
├── core/                       (was state/) — DI + enums + canonical types
│   ├── deps.py                 PipelineDeps (DI container)
│   └── enums.py                StrEnums (Stage, Verdict, ReviewDimension, ...)
├── runtime/                    (was utils/) — cross-cutting runtime utilities
│   ├── context.py              build_context() with revision context injection
│   ├── parsing.py              parse_failure_modes, check_dialogue_health, weakest_dimension
│   ├── dashboard.py            Rich-rendered live dashboard over events.jsonl
│   ├── evaluator.py            Per-node 3-model evaluator panel (Opus-only post-2.4)
│   ├── trace_logger.py         traced_agent_run + bounded_agent_run wiring
│   └── ...                     Checkpoints, validators, score trajectory, throttle, agent_cache
├── tools/                      External API integrations (split into capability sub-packages)
│   ├── bibliography/           Exa search + Semantic Scholar + DOI verification + citation formatter
│   ├── execution/              Sandboxed code execution (AST safety, Docker, sanity)
│   └── rendering/              Pandoc + IEEEtran PDF rendering
└── models/                     Pydantic domain models, split per subgraph (post-2.4)
    ├── research.py             ResearchReport, IndependentVerificationReport, EthicsReviewOutput, ...
    ├── writing.py              DraftSection, FigureVerificationReport, ...
    ├── review.py               EditorReview, PerspectiveReview, ...
    ├── integrity.py            IntegrityReport, ClaimsExtraction, ...
    ├── experiment.py           ExperimentDesign, ExperimentResult, ...
    └── pipeline.py             Top-level orchestrator types
```

Plus at the repo root:

```
configs/                        Runtime tunables (YamlConfigSettingsSource)
├── default.yaml                Defaults (committed)
└── dev.yaml                    Local overrides (gitignored)
examples/                       Runnable SDK examples
docs/architecture/              This document + diagrams
tests/
├── unit/                       Small tests (default — bare `pytest`)
├── integration/                Integration tests (require Docker)
└── medium/                     Marked `medium` — Docker-required scenarios
```

---

## Node Count Summary

Counts reflect actual on-disk state (`grep -c "^class .*Node" graph.py` and `ls specs/*.yaml`) as of 2026-05-04.

| Subgraph  | Nodes | Specs | Internal revision loops |
| --------- | :---: | :---: | ----------------------- |
| Pipeline  | 14 | 0 | Integrity fix loops (Pre + Final), Experiment fix loop |
| Research  | 12 | 15 (12 wired + 3 staged: meta_analysis, monitoring, risk_of_bias) | None — strictly linear forward; per-node evaluator gate replaces DA loops |
| Writing   | 16 | 13 | PeerReviewer → DraftWriter (max rounds via config) |
| Review    | 6  | 12 | None (read-only) |
| Experiment | 7 | 10 | Judge ⇄ InteractiveML loop (max 2 iterations) |
| Integrity | 1  | 2  | None (orchestrator handles fix loops) |
| **Total** | **56** | **52** | |

(The earlier doc claimed 44 nodes / 28 agents. The 12 new nodes and 14 new agents added on 2026-05-04 are all default-off behind config flags — when flags are off, the pipeline behaves identically to the pre-2026-05-04 version.)

---

## SCI Improvements Layer (added 2026-05-04)

Eight independent mechanisms ported from data-to-paper (NEJM AI 2025), Sakana AI Scientist v2, NoveltyAgent, AgentReview, DeepReview, FML-bench, CoI-Agent, and PRISMA-trAIce. All gated behind config flags so the pipeline's pre-2026-05-04 behavior is preserved when flags default off.

### Config flags

| Flag | Default | Spec | What it enables |
|------|---------|------|----------------|
| `traceability_mode` | `"off"` | Spec 1 | `off` / `partial` (validator + Notes appendix) / `full` (+ dialogue + Code appendix) |
| `copilot_enabled` | `False` | Spec 1 | 3 stdin checkpoints (post-intake, post-experiment-design, post-first-draft) |
| `chain_of_ideas_enabled` | `False` | Spec 2 Phase 1 | ChainOfIdeasNode runs alongside KnowledgeGraphNode; populates `state.chain` + `state.thesis` |
| `novelty_gate_enabled` | `False` | Spec 3 Phase 1 | NoveltyGateNode hard-rejects topics with S2 title similarity ≥ `tau_block` (default 0.92) |
| `pointwise_novelty_enabled` | `False` | Spec 4 Phase 1 | Per-claim S2 retrieval; report-only (Phase 2 will force editorial verdict) |
| `persona_reviewers_enabled` | `False` | Spec 5 Phase 1 | 3 persona-anchored reviewers replace existing 3 in ParallelReviewerNode |
| `cascaded_review_enabled` | `False` | Spec 6 Phase 1 | 4-stage cascade: numerical → novelty → methodology → narrative; short-circuit on REJECT |
| `exploration_breadth_enabled` | `False` | Spec 7 Phase 1 | ExperimentDesignNode produces N=4 alternatives → score → pick top K=2 (Phase 1: still runs only top-1) |

(Spec 8 — checklist ethics — is NOT behind a flag. The freeform ethics review was structurally replaced with a 12-item PRISMA-trAIce checklist on 2026-05-04. The agent prompt distinguishes mid-pipeline draft items from submission-time items: `coi_disclosed`, `ai_assistance_disclosed`, and `reproducibility_artifacts_present` are populated by `FinalizeNode` at submission, so absence in a mid-draft auto-waives rather than blocks. See `research/specs/ethics_review.yaml` "Mid-pipeline draft handling (CRITICAL)" section.)

### New models (`src/academic_pipeline/models/`)

| File | Models | Spec |
|------|--------|------|
| `numerical.py` | `NumericalProduct`, `NumericalStore` | Spec 1 |
| `notes.py` | `NoteEntry`, `NotesAppendix` | Spec 1 |
| `ethics.py` | `ChecklistItem`, `EthicsChecklist`, `STANDARD_ITEMS` | Spec 8 |
| `chain.py` | `MilestoneType`, `EdgeRelation`, `Milestone`, `ChainEdge`, `DevelopmentChain`, `ThesisStatement` | Spec 2 |
| `novelty_gate.py` | `NeighborPaper`, `NoveltyGateResult` | Spec 3 |
| `novelty_report.py` | `ContributionClaim`, `ContributionClaimList`, `ClaimAssessment`, `NoveltyReport`, `ClaimNoveltyDimension`, `ClaimVerdict` | Spec 4 |
| `persona_review.py` | `Commitment`, `Intention`, `Knowledgeability`, `PersonaSpec`, `ReviewFinding`, `PersonaReviewOutput` | Spec 5 |
| `cascade.py` | `CascadeStageName`, `StageVerdict`, `StageResult`, `CascadeResult`, `ClaimAuditFinding`, `ClaimAuditReport` | Spec 6 |
| (additions to `experiment.py`) | `DesignAlternative`, `DesignBundle`, `DesignScore`, `SelectedDesigns`, `DesignComparison` | Spec 7 |

All frozen Pydantic (`model_config = ConfigDict(frozen=True)`).

### New module: `src/academic_pipeline/traceability/`

Spec 1's home. Pure receiver-side logic (validators, substitution, appendix generators); producer logic for experiment metrics lives in `src/academic_pipeline/experiment/producers.py` to keep the dependency direction clean.

| File | Purpose |
|------|---------|
| `_patterns.py` | `NUM_TOKEN_PATTERN` regex; single source of truth (imported by validators + substitution) |
| `errors.py` | TRC001-TRC006 typed exceptions |
| `validators.py` | `make_numeric_output_validator()` factory; ports data-to-paper's `get_numeric_value_pattern` regex verbatim |
| `substitution.py` | `substitute_tokens(text, store)` → replaces ⟨num:label⟩ with `\hyperlink{num_<label>}{value}` |
| `notes_appendix.py` | `generate_notes_appendix()` → LaTeX Calculation Notes section with hypertargets + code-link formatting |
| `code_appendix.py` | `generate_code_appendix()` → LaTeX appendix with `\hypertarget{code_<run>_<line>}` at producing lines |
| `context_spec.py` | `ContextSpec(allowed_products, allowed_numerical_labels)` curated-context model |
| `dialogue.py` | `run_writer_reviewer_dialogue()` with PydanticAI `message_history` (helper, not yet wired into writing graph — Phase 2) |
| `copilot.py` | `copilot_checkpoint()` async stdin handler with timeout |

### New experiment module: `src/academic_pipeline/experiment/`

| File | Purpose | Spec |
|------|---------|------|
| `producers.py` | `extract_numerical_products_from_result()` — populates trace store from experiment metrics; supports optional `code` + `code_filename` kwargs for AST line tracing | Spec 1 + line-level provenance |
| `line_tracer.py` | `extract_metric_lines(code)` — AST-walks executed script for `results["label"] = ...` patterns; returns `{label → line_number}` | Line-level provenance |

### Trace chain end-to-end (when `traceability_mode="full"`)

```
Producer (AnalysisNode)
  └─ extract_numerical_products_from_result(result, code, code_filename)
       └─ AST line tracer → source_code_line="analysis.py:42"
       └─ NumericalProduct → state.numerical_store
            ↓
Writer (ParallelSectionDraftNode)
  └─ section_writer agent emits ⟨num:label⟩ tokens
       └─ make_numeric_output_validator() called inline post-run
            ├─ unwrapped numbers → ModelRetry (TRC001)
            ├─ unknown labels → ModelRetry (TRC001)
            ├─ aborting phrases → UnexpectedModelBehavior (TRC002)
            └─ hedge phrases near numbers → ModelRetry (TRC001)
            ↓
Renderer (LatexCompilerNode)
  └─ apply_traceability_substitutions(text, store, mode, runs)
       ├─ substitute_tokens → \hyperlink{num_<label>}{<value>}
       ├─ generate_notes_appendix(store, cited_labels) → Notes \hypertarget per cited entry
       └─ generate_code_appendix(experiment_runs) → Code \hypertarget at producing lines
            ↓
PDF (pandoc + tectonic)
  └─ Reviewer clicks "23.5%" → Notes entry → "analysis.py:42" → exact code line
```

### New nodes added to subgraphs

| Subgraph | Node | Position | Spec |
|----------|------|----------|------|
| Pipeline | `NoveltyGateNode` | After IntakeNode, before ResearchPhaseNode | Spec 3 |
| Research | `ChainOfIdeasNode` | After SynthesisNode, before ReportCompilerNode | Spec 2 |
| Review | `PointWiseNoveltyReviewerNode` | After ParallelReviewerNode, before EditorialSynthesizerNode | Spec 4 |
| Review | `CascadedReviewNode` | After PointWiseNoveltyReviewerNode, before EditorialSynthesizerNode | Spec 6 |
| Experiment | `ExperimentDesignBundleNode` | Replaces ExperimentDesignNode when flag on | Spec 7 |
| Experiment | `DesignSelectionNode` | After ExperimentDesignBundleNode | Spec 7 |
| Experiment | `DesignComparisonNode` | After AnalysisNode (when flag on) | Spec 7 |

### Acknowledged Phase-1 gaps (documented in `docs/architecture/TRACEABILITY.md`)

- **Spec 2:** ChainOfIdeasNode runs alongside (not replacing) KnowledgeGraphNode; the chain isn't yet wired into StructureArchitect; thesis isn't injected into section_writer prompts. Phase 2 will close all three.
- **Spec 3:** PARTIAL verdict (similarity between warn and block thresholds) currently passes through with state note. Phase 2 will add `differentiation_writer` agent + intro-injection.
- **Spec 4:** Editorial synthesizer reads the novelty_report but doesn't yet enforce REJECT verdict on REJECT_NOVELTY. Phase 2 will force the verdict.
- **Spec 5:** Persona reviewers run as alternative to (not in addition to) existing reviewers. Editorial doesn't apply persona-aware aggregation. Phase 2 will compose into the cascade.
- **Spec 6:** Stage D (narrative) is terminal-PASS in Phase 1. Phase 2 will wire actual narrative scoring.
- **Spec 7:** Even with K=2 selected, only the top-1 design's experiment runs. Phase 2 will fan out to K parallel runs.
- **Spec 9 (Cross-run memory):** Intentionally deferred until ≥10 papers shipped through this pipeline.

### Operational hardening (added 2026-05-04, post first end-to-end SCI-flag-on run)

The first full pipeline run with all seven SCI flags enabled (`run-0504-1212_cf0d`) surfaced two real defects in the freshly-merged YAML specs. Both are now fixed and protected by a regression test.

| Defect | Root cause | Fix | Where |
|--------|------------|-----|-------|
| ExperimentDesignBundleNode crashed on first malformed JSON with `Exceeded maximum retries (1) for output validation` | Three new YAMLs (`experiment_designer_bundle`, `design_scorer`, `design_comparator`) shipped without `output_retries`, defaulting to PydanticAI's 1 attempt total. Nested Pydantic schemas (`DesignBundle`/`DesignScore`/`DesignComparison`) make one-shot validation fragile. | Added `output_retries: 3` to all three YAMLs. | `experiment/specs/{design_comparator,design_scorer,experiment_designer_bundle}.yaml` |
| EthicsReviewNode blocked a clean retail-clustering benchmarking paper on `coi_disclosed=False, waiver=null` | The agent correctly observed the mid-draft has no COI section yet (FinalizeNode populates it at submission), but did not synthesize a waiver for the deferred-by-design gap, leaving `waiver=null` which is treated as a hard blocker. | Added "## Mid-pipeline draft handling (CRITICAL)" section to the agent prompt with explicit waiver templates for the three FinalizeNode-populated items (`coi_disclosed`, `ai_assistance_disclosed`, `reproducibility_artifacts_present`). | `research/specs/ethics_review.yaml` |

**Regression test:** `tests/unit/agents/test_yaml_conventions.py` walks every YAML under `src/academic_pipeline/*/specs/` and asserts each agent spec declares `output_retries` (positive integer). Red-green verified — temporarily removing `output_retries` from any spec causes a parametrized test failure naming the offending file. Prevents the "missing output_retries → crash on retry=0" pattern from recurring as new agents are added.
