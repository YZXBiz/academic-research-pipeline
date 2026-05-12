# PRD — Academic Research Pipeline v2.5.0

| Field | Value |
|---|---|
| Project | Academic Research Pipeline (`academic_pipeline`) |
| Anchor version | end of v2.4.0 (currently `[Unreleased]` in `CHANGELOG.md`, working tree on `main` at commit `192091b`) |
| Target version | v2.5.0 |
| Owner | Jackson Yang |
| Audience | LLM agents executing implementation work against this document (Claude / Codex via the superpowers workflow) |
| Source of truth | This file. The CHANGELOG is the version log; this is the contract. |
| Document date | 2026-05-06 |

---

## 1. Executive Summary

The Academic Research Pipeline is an autonomous topic→paper system. One CLI invocation (`make run TOPIC="…"`) produces a journal-ready paper end-to-end: research question formulation, literature search, optional ML experiments in a Dagster + DuckDB + AutoGluon workspace, parallel section drafting, peer review, integrity checks, and PDF compilation through pandoc + tectonic with IEEEtran/ACL templates. Forty-six graph nodes across five subgraphs, thirty-eight PydanticAI agents loaded from YAML specs, all generation and evaluation on Claude Opus 4.7 with `anthropic_effort: max` for reviewer/verifier tier.

The pipeline runs unattended for one to two hours and is built to survive the failure modes that make autonomous AI authoring papers normally fail. A four-layer hang-recovery system (TCP keepalive, bounded `agent.run()`, daemon-thread heartbeat, watchdog supervisor with `SIGTERM`/`SIGKILL` escalation and 3-strikes abort) closes the 1h+ wedged-in-recv class of LLM proxy failures. Crash recovery via `SqliteStatePersistence` + `AgentMessageCache` lets `make resume THREAD_ID=X` pick up at the exact node that died with no work re-typed and no agent dialogue lost. An events.jsonl append-only log is the single source of truth for pipeline progress; the dashboard is a pure renderer over it. Per-node evaluator-optimizer rubrics (max two iterations, default threshold 7.0/10) self-correct locally; an independent verifier agent (`anthropic_effort: max`, 128k tokens) double-checks claims and figures.

This PRD anchors to the end of v2.4.0 and drives v2.5.0. The v2.5.0 milestone closes three buckets of in-flight work: (a) the Dagster experiment template cutover (Phases 0–2 shipped, Phases 3–6 staged), (b) the rendering pivot (figures-via-Dagster, ACL template, longtable→table\* Lua filter for IEEEtran two-column, DOI CrossRef build gate, authors-yaml-required, title-12-words constraint), and (c) Phase 2 wirings of all eight SCI-quality specs (currently shipped at Phase 1 behind off-by-default config flags — Specs 1–8). Phase 2 turns those flags on by default and replaces the legacy paths they shadow. Spec 9 (cross-run memory) is explicitly deferred until 10 papers ship through the new pipeline.

---

## 2. Background and Problem Statement

### 2.1 Why this exists

Producing publication-grade academic output autonomously requires solving five hard problems simultaneously: (1) literature comprehension that does not collapse to a glorified summary, (2) experimental design + execution + analysis that produces results a reviewer cannot dismiss as toy, (3) writing that does not fabricate numbers when synthesis defers, (4) review that catches structural failures rather than vibe-scoring 9/10 to fluff, (5) operational durability across hour-plus generation runs against a flaky upstream proxy. Every existing system optimizes one of these and degrades on the others.

This pipeline is the personal infrastructure of one author producing publication-grade research papers. The bar is peer-reviewed journals, meaning each paper must clear a real peer review, not a preprint server. Supervision is the bottleneck being eliminated, so the pipeline must produce review-ready output unsupervised.

### 2.2 Why now

Three things changed in 2026 Q2:

- **Opus 4.7 with `anthropic_effort: max`** made per-node evaluator-optimizer cycles cheap enough to put on every critical node and a 128k-token verifier on every claim/figure. The previous tier (Opus 4.6 + GPT-5.2 fallback) cost roughly 2x and did not catch the same class of fabrication.
- **Dagster + DuckDB + AutoGluon** matured to the point where an ML lifecycle can be expressed as `@asset` definitions with per-step re-materialization on failure. The prior pipeline's monolithic 440-line `experiment.py` lost 8.5 minutes per failure and re-evaluated by re-reading the entire script every iteration.
- **Internal benchmark exposure** to data-to-paper, AI-Researcher, AIDE, Sakana v1/v2, AgentLab, Kosmos, FML-bench, AgentReview, NoveltyAgent, DeepReviewer-14B, CoI-Agent, and PRISMA-trAIce identified specific structural gaps in the current pipeline (lit-review-feel, fabricated numbers, eval panel blind spots, depth-first refinement collapsing variety, ethics pass-stamps). The eight SCI-quality specs are direct ports from these systems.

### 2.3 What is structurally broken at v2.4.0 that v2.5.0 fixes

The pipeline runs end-to-end and produces papers. The papers do not yet clear SCI peer review consistently. Documented gaps from the project memory and feedback log:

| Gap | Symptom | Origin | Fix in v2.5.0 |
|---|---|---|---|
| Knowledge graph is shallow | KG node uses bib refs as nodes instead of extracting concepts/platforms/domains as first-class entities | `feedback_knowledge_graph_weakness` | Spec 2 Phase 2 — replace KG node with CoI extractor + thesis output |
| Ethics review is a pass-stamp | `EthicsReviewNode` rubber-stamps; misses structural COI patterns | `feedback_ethics_node_shallow` | Spec 8 Phase 2 — replace freeform with 12-item PRISMA-trAIce checklist |
| Writing fabricates numbers | SectionWriter invents pooled estimates / heterogeneity stats / figure callouts even when synthesis defers | `feedback_writing_fabricates_numbers` | Spec 1 Phase 2 — wire trace tokens into rendering and editorial enforcement |
| Eval panel has a blind spot | 3-model panel scored fabricated Results 9/10, fooled by hedge language | `feedback_eval_panel_blind_spot` | Specs 4 (point-wise novelty) + 5 (persona reviewers) + 6 (cascaded gate) Phase 2 |
| Lit review feel | Papers read like summaries instead of arguments with a thesis | `feedback_depth_gaps` (PhD teammate review) | Spec 2 Phase 2 + Spec 7 Phase 2 (exploration breadth) |
| Redundant topics get worked | No early-reject for already-saturated literature | gap analysis | Spec 3 Phase 2 — novelty gate hard-block at S2 title similarity ≥ 0.92 |
| Single experiment design | Depth-first refinement of one design instead of breadth-first across N | FML-bench port analysis | Spec 7 Phase 2 — fan out K parallel design runs |

---

## 3. Goals, Non-Goals, Success Criteria

### 3.1 Goals (v2.5.0)

| # | Goal | Measurement |
|---|---|---|
| G1 | Phase 2 wirings of all 8 SCI specs live and on by default | Each Phase 2 spec's `*_enabled` config flag defaults to `true`; Phase 1 codepaths deleted or behind a `legacy_*` flag |
| G2 | Dagster experiment template covers Stages 3–6 | classification/regression, timeseries, multimodal, DVC dataset versioning all reachable via `config.yaml`; `make run-experiment` exercises each in CI |
| G3 | Rendering pivot lands | figures-via-Dagster (PNG copy from `02-experiment/`), ACL template, `longtable-to-table-star.lua` Lua filter, DOI CrossRef build gate, `authors.yaml` required, title 12-word constraint enforced — all default behavior |
| G4 | One paper from this version clears SCI peer review | tracked externally (the journal's editorial decision) |
| G5 | Test suite continues to grow with deltas | `make test` ≥ 1500 unit tests, `make test-integration` green |
| G6 | No regression in operational durability | `make run-experiment` survives ≥10 consecutive runs against LLM proxy without manual intervention; `make resume THREAD_ID=X` resumes from any node |
| G7 | Observability stays whole | `events.jsonl` schema additions for new nodes; dashboard renders new SCI gates (cascade verdicts, novelty scores) |

### 3.2 Non-Goals (explicit, scoped out of v2.5.0)

The autonomous loop will read this list and refuse to scope work into these areas without an explicit user directive.

| # | Non-goal | Reason |
|---|---|---|
| N1 | Web frontend | The CLI + Logfire + dashboard.txt cover the operator surface. A web UI is out of scope until at least three external users exist. |
| N2 | Multi-paper portfolio mode | One run = one paper. Cross-run state is Spec 9 territory and gated on 10 shipped papers. |
| N3 | Journal submission automation | Submitting to journals requires real author identity, manuscript-tracking-system credentials, and editorial correspondence handling. Out. |
| N4 | Co-author dashboard / multi-user | Single-author tool. No accounts, no permissions, no sharing. |
| N5 | Browser-based agent dispatch | All agents run in-process via PydanticAI. No remote workers, no Lambda, no Kubernetes. |
| N6 | Replacing Anthropic as the primary model provider | Opus 4.7 is the model. Multi-provider orchestration is not a v2.5.0 concern. |
| N7 | Spec 9 cross-run memory (AgentRxiv port) | Deferred to Section 7. Do not start. |
| N8 | Visual regression for figures | Figures are accepted if VLM verifier passes and matplotlib emits a PDF/PNG. Pixel-level diffing is unnecessary at this scale. |
| N9 | Custom LaTeX engine | tectonic via pandoc only. No latexmk, no XeLaTeX swap-in, no custom build script. |
| N10 | Replacing Dagster with another orchestrator | Dagster + DuckDB + MLflow + DVC is the experiment substrate. Do not propose Prefect, Airflow, Metaflow, etc. |

### 3.3 Success criteria — "v2.5.0 done"

Two tiers. **Code/process gates** (1–8) verify the changes landed cleanly. **Output gates** (9–13) verify the pipeline actually produces good papers — passing the first eight does not imply passing the latter, and v2.5.0 is releasable only when **all 13** hold.

**Code / process gates**

1. Every config flag listed in `config.py` for the 8 SCI specs (`traceability_mode`, `chain_of_ideas_enabled`, `copilot_enabled`, `novelty_gate_enabled`, `pointwise_novelty_enabled`, `persona_reviewers_enabled`, `cascaded_review_enabled`, `exploration_breadth_enabled`) has its Phase 2 wiring complete — meaning the legacy codepath it shadows is either removed or behind a `legacy_*` flag, and the new behavior is the default.
2. `make check` passes (`ruff` clean, `pyright` clean, `pytest` ≥ 1500 tests green).
3. `make test-integration` green against Docker.
4. `make run-experiment TOPIC="<sample>"` produces a `.pdf` from a Dagster experiment in ≤ 2 hours, supervised, against LLM proxy.
5. `make resume THREAD_ID=<crashed-run>` restores from any node mid-pipeline.
6. CHANGELOG entry for v2.5.0 written and dated.
7. `examples/` contains one runnable script per cross-cutting capability added.
8. PRD §6 deltas all show every task as `[x]` (done) or `[skipped]` with rationale.

**Output gates** (the actual product bar — see §6.15)

9. All 5 golden fixture topics pass the full structural-assertion suite (`make test-regression` Phase A green).
10. All 6 LLM-as-Judge evaluators (hedge-language, thesis-coherence, persona-tone-mismatch, citation-orphan, fabricated-numeric, IMRaD-completeness) achieve **TPR ≥ 0.85 AND TNR ≥ 0.85** on their respective held-out test splits.
11. Bias-corrected true pass rate per failure mode has **95% bootstrap CI lower bound ≥ 0.70** on a rolling sample of 50 production runs (Rogan-Gladen correction over judge predictions; see §6.15.T7).
12. Jackson signs off on **3 randomly-selected sample papers** end-to-end (recorded as checked boxes + signature lines in `docs/v2.5.0-spot-review.md`). The release tag does not get pushed until this file is signed — see §11. The "is v2.5.0 better than v2.4.0" judgment lives here: at least one of the 3 papers must be on a topic that has a v2.4.0 baseline run, and Jackson eyeballs the two side-by-side. No formal A/B testing — your taste is the gate.

---

## 4. Stakeholders and Ownership

| Role | Identity | Responsibility |
|---|---|---|
| Owner | Jackson Yang | Final scope decisions, release cuts, paper submission |
| Reviewer (technical) | PhD teammate (per `feedback_depth_gaps`) | Reads generated papers and flags structural quality issues |
| Implementer | LLM agents (Claude Opus 4.7 / Codex via superpowers) | Execute deltas in §6 against this PRD |
| Operator | Jackson Yang | Runs `make run-experiment`, monitors via Logfire, files crash bugs |
| External: model | Anthropic (Opus 4.7) | All generation + reviewer/verifier; failure mode = LLM proxy hang (closed by §6.6) |
| External: model (deprecated) | OpenAI | No longer used as of v2.4.0. SDK wired for legacy compat only. |
| External: search | Exa | Bibliography + dataset discovery (`web_search_exa`, `web_fetch_exa`) |
| External: bibliographic | CrossRef | DOI validation, retraction checks |
| External: bibliographic | Semantic Scholar | Novelty gate (Spec 3), point-wise novelty reviewer (Spec 4) |
| External: observability | Pydantic Logfire | Project `research-demo` |
| External: rendering | tectonic, pandoc, IEEEtran/ACL | LaTeX → PDF compilation |
| External: experiment substrate | Dagster, DuckDB, AutoGluon, MLflow, DVC | Workspace template |
| External: sandbox | Docker | Experiment execution isolation (subprocess fallback) |

---

## 5. Architecture Overview

### 5.1 Pipeline flow (44 nodes / 5 subgraphs)

```
IntakeNode
    ↓
[NoveltyGateNode]                         ← Spec 3 Phase 1 (off by default)
    ↓
ResearchPhaseNode (subgraph)
    ↓
ExperimentClassifierNode
    ├── needs_experiments=true → ExperimentPhaseNode (subgraph, Dagster template)
    │                                ├── failure + retries left → retry inline (no separate `ExperimentFixNode` — verified absent in `pipeline/nodes.py`; retry counter `PipelineState.experiment_fix_count`)
    │                                └── failure + max retries → AbortNode
    └── needs_experiments=false → (skip)
    ↓
WritePhaseNode (subgraph)
    ↓
PreIntegrityNode
    ↓
ReviewPhaseNode (subgraph)
    ├── [PointWiseNoveltyReviewerNode]    ← Spec 4 Phase 1 (off)
    ├── [PersonaReviewerPanelNode]        ← Spec 5 Phase 1 (off)
    └── [CascadedReviewNode]              ← Spec 6 Phase 1 (off)
    ↓
FinalIntegrityNode
    ↓
FinalizeNode → SummaryNode → End
```

State persists between phases via `pydantic.TypeAdapter`-serialized `PipelineState` to `.pipeline_runs/<thread-id>_state.json`. The `events.jsonl` append-only log under `output/<run-id>/` is the single source of truth for pipeline progress; the dashboard is a pure renderer over it (see §6.8).

### 5.2 Subgraph map

| Subgraph | Code | Specs | Nodes | Purpose |
|---|---|---|---|---|
| Research | `src/academic_pipeline/research/` | 15 YAML in `research/specs/` | 11 | RQ formulation, methodology, bibliography (Exa), source verification, knowledge graph, synthesis, independent verification, editorial + ethics review |
| Experiment | `src/academic_pipeline/experiment/` | 11 YAML in `experiment/specs/` | 7 (was 9 pre-2026-05-04) | Classifier → designer → config_writer → Dagster run → analysis. Dagster template at `templates/dagster-experiment/`. |
| Writing | `src/academic_pipeline/writing/` | 13 YAML in `writing/specs/` | 16 | Outlining, argument building, parallel section drafting, citation audit, abstract, figure curator, peer review, formatting |
| Review | `src/academic_pipeline/review/` | 12 YAML in `review/specs/` | 4 (+3 with Phase 2) | Field analysis, 3 parallel reviewers, editorial synthesis. Spec 5 swaps the 3 reviewers for personas; Spec 6 wraps with cascaded gate. |
| Integrity | `src/academic_pipeline/integrity/` | 2 YAML in `integrity/specs/` | 1 (composite) | Claims extraction, plagiarism heuristics, AI style detection. Spec 8 Phase 2 replaces freeform ethics with 12-item checklist. |

### 5.3 Cross-cutting systems map

| System | Code | Purpose |
|---|---|---|
| Recovery | `src/academic_pipeline/recovery/` (`transport.py`, `bounded_run.py`, `heartbeat.py`, `process_state.py`, `supervisor.py`, `watchdog.py`) | 4-layer hang-recovery (TCP keepalive → bounded `agent.run()` → daemon-thread heartbeat → watchdog SIGTERM/SIGKILL escalation) |
| Rendering | `src/academic_pipeline/runtime/paper_renderer.py`, `runtime/citation_resolver.py`, `tools/rendering/latex_compiler.py`, `templates/pandoc/` | pandoc + tectonic compile, IEEEtran/ACL templates, `longtable-to-table-star.lua` filter, figures-via-Dagster (PNG copy from `02-experiment/`), DOI gate |
| Dashboard + Events | `src/academic_pipeline/runtime/dashboard.py`, `runtime/events.py`, `output/<run-id>/events.jsonl`, `output/<run-id>/dashboard.txt` | Append-only event log + pure-renderer dashboard. CLI: `python -m academic_pipeline dashboard --watch --latest` |
| Persistence + AgentCache | `src/academic_pipeline/persistence.py`, `tools/agent_cache.py` | `.pipeline_runs/<thread-id>_state.json` for graph state; `AgentMessageCache` for PydanticAI message history (judge loop resume, crash recovery) |
| Traceability | `src/academic_pipeline/traceability/` (`copilot.py`, `dialogue.py`, `code_appendix.py`, `notes_appendix.py`, `substitution.py`, `validators.py`, `errors.py`, `context_spec.py`) | SCI-traceability port (Spec 1). Trace tokens, dialogue helpers, code/notes appendices, substitution, point-wise validators, line-level provenance via `experiment/line_tracer.py` |
| Quality Gate | `src/academic_pipeline/runtime/evaluator.py`, `runtime/hard_vetos.py`, `runtime/score_trajectory.py`, the `independent_verifier` and `figure_verifier` agents | Per-node evaluator-optimizer (max 2 iterations, default threshold 7.0/10), independent verification (Opus 4.7 + `anthropic_effort: max`, 128k tokens), VLM figure review |
| Config + SDK Surface | `src/academic_pipeline/config.py`, `configs/default.yaml`, `configs/dev.yaml`, `src/academic_pipeline/__init__.py`, `src/academic_pipeline/sdk/`, `examples/`, `skills/` | Pydantic-settings config (init > env > .env > dev.yaml > default.yaml), public API (`Pipeline`, `PipelineConfig`, `PipelineResult`, `DEFAULT_CONFIG`), `py.typed` marker, skill packs loaded from `SKILLS_DIRS` |
| Observability | `src/academic_pipeline/observability.py`, `src/academic_pipeline/logging_config.py` | Logfire (`instrument_pydantic_ai`, `instrument_httpx(capture_all=True)`), `send_to_logfire="if-token-present"` for graceful degradation, structured Python logging with rotating file handler |
| CI / Release Pipeline | `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `Makefile`, `pyproject.toml`, `VERSION`, `CHANGELOG.md` | lint + typecheck + test matrix on Python 3.12/3.13 self-hosted runners; tag-triggered publish workflow; version unification across `VERSION` / `pyproject.toml` / README badges |
| Output Verification + LLM-as-Judge | `tests/fixtures/golden/`, `tests/fixtures/labeled_traces/`, `tools/output_assertions.py`, `tools/abtest.py`, `src/academic_pipeline/evaluation/` | Golden reference fixtures, code-based structural assertions, per-failure-mode LLM-as-Judge evaluators with train/dev/test splits, Rogan-Gladen bias correction + bootstrap CI, A/B comparator, human spot-review checkpoint |

### 5.4 SCI roadmap status table

All 8 specs Phase 1 shipped on main as of 2026-05-04. Each is behind an off-by-default config flag. v2.5.0 closes Phase 2 for each.

| Spec | Title | Source | Phase 1 status | Phase 2 owner-component | v2.5.0 |
|---|---|---|---|---|---|
| 1 | Traceability port | data-to-paper / NEJM AI | Shipped (`traceability_mode: off`); line-level provenance shipped 2026-05-04 (commit `25076b9`) | §6.10 Traceability + §6.3 Writing | `traceability_mode: full` default, dialogue helper wired, per-agent ContextSpec rollout |
| 2 | Chain-of-Ideas KG | CoI-Agent | Shipped (`chain_of_ideas_enabled: false`) | §6.1 Research | Replace `KnowledgeGraphNode` entirely with CoI + thesis extractor |
| 3 | Novelty gate | Sakana v2 | Shipped Phase 1 (`novelty_gate_enabled: false`, hard-reject only at `tau_block: 0.92`) | §6.1 Research | Default on; soft-warn at `tau_warn: 0.78` integrated into RQ refinement |
| 4 | Point-wise novelty reviewer | NoveltyAgent | Shipped (`pointwise_novelty_enabled: false`) | §6.4 Review | Default on; output enforced by editorial synthesis |
| 5 | Persona reviewer panel | AgentReview | Shipped (`persona_reviewers_enabled: false`) | §6.4 Review | Default on; replaces default 3 reviewers with senior_gatekeeper / applied_practitioner / methodology_purist |
| 6 | Cascaded reviewer | DeepReviewer-14B | Shipped (`cascaded_review_enabled: false`); composes 1+4+5 | §6.4 Review | Default on; editorial synthesis enforces cascade verdict |
| 7 | Exploration breadth | FML-bench | Shipped Phase 1 (`exploration_breadth_enabled: false`, scoring/selection only — only top design runs) | §6.2 Experiment + §6.3 Writing | K parallel design fan-out actually runs; StructureArchitect requires thesis-advancing per-section roles |
| 8 | Checklist ethics | PRISMA-trAIce | Shipped (replaces freeform ethics review when on) | §6.5 Integrity + §6.1 Research | Default on; freeform `EthicsReviewNode` deleted |
| 9 | Cross-run memory | AgentRxiv | Not started | n/a | **Deferred** (see §7) |

### 5.5 Reading order for autonomous agents

The 15 components in §6 (12 original + 6.13 Observability + 6.14 CI/Release + 6.15 Output Verification) are not independent. An autonomous loop picking components in arbitrary order will hit `BLOCKED` on prerequisites that have not landed yet. Use this dependency table to derive phase ordering in any plan derived from this PRD.

**Hard depends on** = component cannot start until prerequisite is done. Attempting to start anyway will fail tests or fail to compile.

**Soft depends on** = component can start, but quality / verification is shakier without prerequisite. Acceptable to interleave, but verify the prerequisite is at least at "Current state" sanity before merging.

| Component | Hard depends on | Soft depends on |
|---|---|---|
| 6.1 Research subgraph | 6.11, 6.12 | 6.10 |
| 6.2 Experiment subgraph | 6.11, 6.12 | 6.7, 6.9 |
| 6.3 Writing subgraph | 6.7, 6.10, 6.11 | 6.2 (figures-via-Dagster) |
| 6.4 Review subgraph | 6.10, 6.11 | 6.1 (CoI thesis output) |
| 6.5 Integrity subgraph | 6.10 | 6.4 (cascade verdict) |
| 6.6 Recovery | — | 6.9 (state-resume integration) |
| 6.7 Rendering | 6.9 | 6.10 (provenance markers in PDF) |
| 6.8 Dashboard + Events | 6.9 | 6.6 (heartbeat events) |
| 6.9 Persistence + AgentCache | 6.12 | — |
| 6.10 Traceability | 6.12 | 6.8 (event markers for trace tokens) |
| 6.11 Quality Gate | 6.12 | — |
| 6.12 Config + SDK Surface | — | — |
| 6.13 Observability | 6.8 | 6.6 (recovery events surface in traces) |
| 6.14 CI / Release Pipeline | 6.12 | 6.6, 6.9 (test surface for hang + resume) |
| 6.15 Output Verification + LLM-as-Judge | 6.4, 6.10, 6.11 (cascade verdict, trace tokens, eval rubrics are inputs to the judges) | 6.13 (judges traced via Logfire), 6.14 (regression suite plugs into CI) |

**Topological execution order** (one valid linearization):

```
6.12  →  { 6.6, 6.9, 6.11, 6.14 }  →  { 6.10, 6.8 }  →  { 6.13, 6.7 }  →  { 6.1, 6.2, 6.5 }  →  { 6.3, 6.4 }  →  { 6.15 }
```

**Special case for 6.15.** The error-analysis labeling sub-stages (T4a–T4e) can start in **Phase 0** in parallel with everything else, because labeling 100+ historical traces from `output/` archive does not depend on Phase 2 wirings. The judge construction (T5–T6) and regression suite (T8) wait for Phase 5 to land so the judges score Phase-2 outputs, not Phase-1.

Components inside `{…}` are independent and may be parallelized by separate agents/sessions. The sequencing in §10 elaborates this with task-level granularity.

---

## 6. Component Catalog

Every component below uses the same six-field structure:

- **Purpose** — one-paragraph statement of what this component is for.
- **Contract** — inputs, outputs, success criteria as a black-box specification.
- **Current state (end of v2.4.0)** — files on main, test count, what works today.
- **Target state (v2.5.0)** — what the component must do when v2.5.0 ships.
- **Delta** — sequenced task list (3–15 tasks per component) with stable IDs.
- **Verification** — exact shell command(s) that prove the component meets its target state. An autonomous loop must run this and read the exit code; do not hallucinate success.

Task IDs use the form `<component>.T<n>` (e.g. `6.1.T3`). Stable across PRD revisions.

---

### 6.1 Research subgraph

**Purpose.** Take a research topic (free text, optionally + revision directive), produce a structured research artifact: refined research question, methodology blueprint, verified bibliography (≥20 sources, ≥50% from last 3 years), knowledge graph, synthesis with thesis, editorial + ethics review verdicts, independent verification report.

**Contract.**
- *Inputs:* `topic: str`, `revision: Optional[str]`, `PipelineDeps` (HTTP client, agent registry, config).
- *Outputs:* `ResearchState` containing `ResearchQuestion`, `MethodologyBlueprint`, `Bibliography`, `KnowledgeGraph` (or `ChainOfIdeas` + `Thesis` post-Spec-2-Phase-2), `Synthesis`, `EditorReview`, `EthicsReview` (or `EthicsChecklist` post-Spec-8-Phase-2), `IndependentVerificationReport`.
- *Success criteria:* every node passes its rubric (default threshold 7.0/10). DOI-verified sources marked `verified=True`. No `[MATERIAL GAP]` flags in synthesis. Independent verifier returns `Verdict.PASS` or `Verdict.PASS_WITH_CONDITIONS` (the verified enum value at `core/enums.py:62-67` is `PASS_WITH_CONDITIONS`, **NOT** `PASS_WITH_NOTES`; full Verdict set: PASS, PASS_WITH_CONDITIONS, REVISE, FAIL, BLOCKED, CLEARED).

**Current state (end of v2.4.0).**
- 11 nodes in `src/academic_pipeline/research/graph.py` (1112 lines).
- 15 YAML specs in `research/specs/`: `research_question`, `research_architect`, `bibliography`, `source_verification`, `knowledge_graph`, `synthesis`, `report_compiler`, `meta_analysis`, `monitoring`, `risk_of_bias`, `editor_in_chief`, `ethics_review`, `independent_verifier`, `chain_of_ideas_extractor`, `thesis_extractor`.
- Phase 1 of Specs 2 (CoI), 3 (novelty gate), 8 (checklist ethics) shipped behind flags.
- `chain_of_ideas_extractor.yaml` + `thesis_extractor.yaml` run alongside `KnowledgeGraphNode` when `chain_of_ideas_enabled=true`. Output is captured in state but not yet consumed downstream.
- `NoveltyGateNode` (`research/novelty_gate.py`) hard-rejects topics with S2 max title similarity ≥ `novelty_gate_tau_block` (0.92). Lives between intake and research.
- Tests in `tests/unit/research/`; integration coverage in `tests/integration/test_research_graph.py`.

**Target state (v2.5.0).**
- `chain_of_ideas_enabled` defaults to `true`; `KnowledgeGraphNode` deleted; `ChainOfIdeas` + `Thesis` are the canonical research outputs consumed by Writing (StructureArchitect + ArgumentBuilder) and Review (cascade Stage C).
- `novelty_gate_enabled` defaults to `true`; soft-warn at `tau_warn` (0.78) feeds back into RQ refinement (one extra `ResearchQuestionNode` iteration with a hint), hard-block at `tau_block` aborts before research.
- Thesis is a first-class field on `ResearchState`, asserted non-empty by an `output_validator` on `synthesis`.
- `ethics_review.yaml` deleted; replaced by Integrity subgraph's `EthicsChecklistNode` consuming research outputs (see §6.5).
- All research nodes' rubrics include a "thesis-advancing" dimension (PASS requires >=7).

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.1.T1 | Flip `chain_of_ideas_enabled` default to `true` in `config.py` and `configs/default.yaml`. Add `legacy_knowledge_graph` flag (default `false`) to keep escape hatch. | XS |
| 6.1.T2 | Modify `research/graph.py` so `KnowledgeGraphNode` only runs when `legacy_knowledge_graph=true`; otherwise **`ChainOfIdeasNode`** (a SINGLE node, per Spec 2 design doc — calls `chain_of_ideas_extractor` agent then `thesis_extractor` agent in sequence) is the canonical path. Update `ResearchState` to make `chain` (DevelopmentChain) and `thesis` (ThesisStatement) non-optional, `knowledge_graph` optional. PRD ralph-1..36 incorrectly implied two separate nodes (`ChainOfIdeasExtractorNode` + `ThesisExtractorNode`) — Spec 2 design doc clarifies it's one node, two agent calls. The agent registry keys (`chain_of_ideas_extractor` + `thesis_extractor`) are correct as documented. | M |
| 6.1.T3 | Add `output_validator` to `synthesis` agent that asserts `thesis` is present and non-empty. Wire `Thesis` as required input to synthesis. | S |
| 6.1.T4 | Update `_RUBRIC_SYNTHESIS` to include "Thesis advancement" dimension. Update tests that expect old rubric text. | S |
| 6.1.T5 | Flip `novelty_gate_enabled` default to `true`. Wire PARTIAL-verdict (S2 max similarity ∈ [0.78, 0.92)) to one of two designs — **decide first**: (a) Spec 3 design doc says generate a `differentiation_paragraph` via a new agent and require it to appear in the introduction; (b) Pragmatic alternative: trigger one extra `ResearchQuestionNode` iteration with the top-3 conflicting titles injected as hint. Both are reasonable. Recommendation: implement (a) per spec — it's the more rigorous approach and produces an artifact downstream writers can cite. **Decision required from Jackson before implementation.** | M |
| 6.1.T6 | Delete `research/specs/ethics_review.yaml` and `EthicsReviewNode` from `research/graph.py`. **Also delete `EthicsReviewOutput` Pydantic class at `models/research.py:395`** (verified ralph-48 — it's the output type of the agent being deleted; orphan class otherwise). Move the contract to §6.5 Integrity. Update `tests/unit/research/test_ethics_review.py` (delete) and `tests/integration/test_research_graph.py` (assert ethics step absent in research, present in integrity). | M |
| 6.1.T7 | Delete `KnowledgeGraphNode` class once 6.1.T2 is verified. Drop `knowledge_graph.yaml`. **Also delete `KnowledgeGraph` Pydantic class at `models/research.py:227`** + `SourceRelationship` (`:204`) + `ResearchCluster` (`:216`) — all 3 are KnowledgeGraph-specific output types that become orphan when the node is gone. Update all imports. | S |
| 6.1.T8 | Wire `ChainOfIdeas` + `Thesis` into `ResearchPhaseNode` exit so they reach `WritePhaseNode` via `PipelineState.research_artifact`. Update `models/research.py` accordingly. | S |
| 6.1.T9 | Add 5 new unit tests in `tests/unit/research/test_chain_of_ideas_phase2.py` verifying: thesis is non-empty after synthesis, KG path absent under default flags, KG path present under legacy flag, novelty soft-warn triggers RQ refinement, novelty hard-block aborts before bibliography. | M |

**Verification.**
```bash
uv run pytest tests/unit/research/ tests/integration/test_research_graph.py -x -q && \
uv run python -c "from academic_pipeline.config import PipelineConfig; c = PipelineConfig(); assert c.chain_of_ideas_enabled and c.novelty_gate_enabled, 'flags not flipped'; print('OK')"
```

---

### 6.2 Experiment subgraph

**Purpose.** When the topic benefits from computational experiments, design the experiment, find real public datasets via Exa, generate a `config.yaml` for a Dagster + DuckDB + AutoGluon workspace, execute it, analyze results with domain-theoretic context, replicate across multiple seeds, and surface verified `ExperimentResults` for the writing phase to cite.

**Contract.**
- *Inputs:* `ResearchState` (RQ + methodology + thesis), `PipelineDeps`, `experiment_seeds` (default `[42, 123, 456]`).
- *Outputs:* `ExperimentResults` with verified dataset URLs, MLflow run ID, multi-seed metrics (mean ± std), figures (`.png` paths under `output/<run-id>/02-experiment/`), domain-theoretic analysis, `results.json`. State `ExperimentState` deserializable for resume.
- *Success criteria:* all sanity checks pass (`sanity_check_results`, `verify_plan_alignment`, `verify_dataset_urls`); monotonic quality gate not violated (improvement loop reverts if metric worsens); at least one figure produced; `results.json` validates against `ExperimentResults` schema.

**Current state (end of v2.4.0).**
- **`experiment/dagster_runner.py`** (verified ralph-62) — subprocess invocation of `dagster job execute`:
  - `run_dagster_job(workspace: Path, timeout_s: int = 1800) -> DagsterRunResult` — two-step subprocess chain:
    1. `uv sync` in workspace (timeout **600s = 10 min, hardcoded NOT configurable**)
    2. `uv run dagster job execute -m pipeline.definitions` (`timeout_s` configurable, matches `experiment_timeout_seconds=1800` per config.py)
  - **2 pre-flight `FileNotFoundError` checks**: `config.yaml` must exist in workspace; `src/pipeline/definitions.py` must exist (per Python import resolution for `-m pipeline.definitions`)
  - **Template-to-workspace structure preservation** (verified ralph-63 via `template_copier.py` + actual `templates/dagster-experiment/` `ls`): the template ALREADY has `src/pipeline/definitions.py` at its root (verified actual top-level dirs: `.dg/`, `examples/`, `src/`, `tests/`, plus `pyproject.toml`, `README.md`, etc.). The copier preserves structure — it does NOT transform `pipeline/` into `src/pipeline/`. **Earlier PRD claim of a "pipeline/ → src/pipeline/" transformation was incorrect — fixed in ralph-63.** When `template_copier.copy_template_into(workspace)` runs, `src/pipeline/definitions.py` lands at `<workspace>/src/pipeline/definitions.py` directly. Loop modifying the template (§6.2.T1) must add new strategies to `templates/dagster-experiment/src/pipeline/strategies/` — NOT `templates/dagster-experiment/pipeline/strategies/` (that path doesn't exist).
  - `DagsterRunResult` dataclass: `succeeded: bool` (computed as `returncode == 0 AND results_path.exists()` — both required, returncode 0 alone is insufficient because Dagster can exit 0 but fail to write `results.json`), `returncode`, `results_json_path`, `stdout`, `stderr`.
  - `load_results_json(path) -> dict` — separate utility for reading the results.json file.
- 9 node classes in `src/academic_pipeline/experiment/graph.py` (verified at HEAD): `ExperimentDesignNode` (NOT "Designer" — the agent registry KEY is `experiment_designer` but the node CLASS is `ExperimentDesignNode`), `ExperimentDesignBundleNode` (same naming asymmetry — agent key `experiment_designer_bundle`, node class `ExperimentDesignBundleNode`), `DesignSelectionNode`, `DesignComparisonNode`, `InteractiveMLNode` (deprecated, to delete in §6.2.T7), `JudgeNode` (deprecated, to delete), `ConfigWriterNode`, `DagsterRunNode`, `AnalysisNode`. Note: `ExperimentClassifierNode` lives in the OUTER graph at `pipeline/nodes.py`, not in the experiment subgraph. **No separate `ImprovementNode` or `MultiSeedNode` classes exist** — improvement loop logic lives inline in `AnalysisNode`/orchestrator and uses the `experiment_improver` agent yaml; multi-seed replication is also inline.
- **5-layer enforcement harness** in `experiment/harness.py` (verified ralph-46) protects the InteractiveMLNode tool surface:
  1. **Layer 1 (PrepareTools)** `_enforce_template_first` — forces template call before container tools
  2. **Layer 2 (before_tool_execute)** `block_raw_ml_imports` — blocks 14 raw ML library imports
  3. **Layer 3 (after_tool_execute)** `mark_template_called` — marks template as called
  4. **Layer 4 (after_tool_execute)** `post_run_sensor` — sensor on `results.json`
  5. **Layer 5 (output_validator)** `validate_experiment_output` / `validate_experiment_plan` — validates `ExperimentComplete` has real results
- **`FORBIDDEN_IMPORTS` frozenset** (14 entries, verified `harness.py:32-43`): `import lightgbm`, `import xgboost`, `import catboost`, `from lightgbm`, `from xgboost`, `from catboost`, `from sklearn.ensemble`, `from sklearn.linear_model`, `from sklearn.svm`, `from sklearn.tree`, `from sklearn.neural_network`, `from statsforecast`/`import statsforecast`, `from gluonts`/`import gluonts`, `from chronos`/`import chronos`, `from transformers`/`import transformers`, `from timm`/`import timm`. Loop must update this set if adding new restricted libraries.
- **`ALLOWED_SKLEARN` frozenset** (4 entries): `from sklearn.dummy`, `from sklearn.model_selection`, `from sklearn.metrics`, `from sklearn.preprocessing`. Anything else from sklearn is blocked.
- **`ALLOWED_AUTOGLUON` frozenset** (5 entries): `from autogluon.tabular`, `from autogluon.timeseries`, `from autogluon.multimodal`, `from autogluon.core`, `import autogluon`.
- **`TEMPLATE_MAP` dict** (3 entries) at `harness.py:60`: `"tabular"` → `get_autogluon_tabular_template`, `"timeseries"` → `get_autogluon_timeseries_template`, `"multimodal"` → `get_autogluon_multimodal_template`. Loop adding a new problem type (e.g., `"unsupervised"`) must extend this map.

**Architectural question (open) — what happens to `harness.py` after §6.2.T7 deletes InteractiveMLNode?** Three possibilities, Jackson must decide: (a) delete harness.py too — `ConfigWriter` agent only writes YAML, no ML imports to block; (b) port the harness to ConfigWriter as a defensive layer for any LLM-emitted YAML that gets passed to Dagster strategies; (c) keep as defensive infrastructure for any future tool-using agents. Recommendation: (a) delete in §6.2.T7 since post-Dagster the agent has no executable surface to constrain. **Surfaced as new OQ.**
- 11 YAML specs in `experiment/specs/`: `experiment_classifier`, `experiment_designer`, `experiment_designer_bundle`, `design_comparator`, `design_scorer`, `config_writer`, `ml_engineer` (deprecated), `experiment_improver`, `experiment_judge` (deprecated), `result_analyzer`, `figure_reviewer`.
- **`assets/_common/data_load.py` `@asset` (verified ralph-67, 73 lines)** — fixed infra that materializes raw DuckDB tables from `dataset.source`. **CRITICAL DAGSTER ANTI-PATTERN** (per docstring lines 5-8): `from __future__ import annotations` MUST BE OMITTED in any module containing `@asset`/`@asset_check`. Reason: "Dagster's `@asset` decorator inspects parameter annotations at runtime and does identity comparisons (e.g. context arg must BE `AssetExecutionContext`, not the string `"AssetExecutionContext"`). PEP 563 deferred annotations break that check." This is the OPPOSITE of the rest of the codebase pattern (which always uses `from __future__ import annotations`). Loop generating per-experiment `@asset` modules in `assets/experiment/*` MUST omit the future import. Without this, Dagster fails to register the assets at job execute. **`raw_data` @asset signature**: `context: AssetExecutionContext`, `app_config: ConfigResource`, `duckdb: DuckDBResource` → returns `dict[str, int]` (`{table_name: row_count}`). `group_name="_common"` for Dagster UI grouping. **Table-naming convention**: `f"raw_{Path(filename).stem.replace('-', '_')}"` — dashes converted to underscores for SQL safety. **CSV loading uses `sample_size=-1` + `null_padding=true`** (verified comment at lines 36-41) — defaults would silently corrupt datasets where early rows look like one type but later rows have a wider range (e.g. rossmann's `StateHoliday`: BIGINT in early rows, then `"a"`/`"b"`/`"c"`). Loop generating new CSV-reading code MUST preserve these options. **3 supported source schemes**: `huggingface://org/repo` (via `hf_hub_download(repo_id=..., filename=..., repo_type="dataset")`), `file://path` (local), `http(s)://...` (DuckDB direct URL read), plus fallback "treat as local path" for tests/fixtures. **2 supported extensions only**: `.csv`, `.parquet`/`.pq`. Anything else raises `ValueError(f"Unsupported file extension: {ext}")`. Loop adding new format support must extend the dispatch.
- **`resources.py` actual API** (verified ralph-66, 65 lines): 3 resource classes + 3 helpers. (a) `workspace_dir() -> Path` returns `Path.cwd()` — Dagster process is launched with `cwd = workspace/` per dagster_runner; resources resolve paths against this. (b) `ConfigResource(ConfigurableResource)` with `config_path: str = "config.yaml"` and `_cached: ExperimentConfig | None = PrivateAttr(default=None)`; `get()` lazy-loads + validates via `yaml.safe_load` (NOT `yaml.load` — security-critical) + `ExperimentConfig.model_validate`; idempotent caching. (c) `make_duckdb_resource() -> DuckDBResource` at `workspace/experiment.duckdb` — **single store for all materializations** (architectural invariant — loop must NOT add multiple .duckdb files). (d) `MLflowResource(ConfigurableResource)` with `experiment_name: str = "experiment"` default; tracking URI file-backed at `workspace/mlruns/` (`file://...`); lazy-configured via `_configured: bool` PrivateAttr. **Pattern for asset MLflow runs**: "Each asset opens nested runs via `mlflow.start_run(nested=True)`" — loop generating @asset code must use `nested=True`. **3 fixed workspace paths**: `workspace/config.yaml` (input from config_writer), `workspace/experiment.duckdb` (single output store), `workspace/mlruns/` (file-backed MLflow).
- **`config_models.py` actual schema** (verified ralph-65): only 4 top-level fields on `ExperimentConfig` — `schema_version: Literal[1] = 1`, `dataset: DatasetConfig` (with 4 fields: `source` accepting `huggingface://org/repo` | `file://path` | `http(s)://url`, `files: list[str]`, `entity_id_column: str` (NEVER used as a feature — explicit constraint), `date_column: str | None`), `mlflow: MLflowConfig` (default-constructed), `reproducibility: ReproducibilityConfig` (default `random_seed=42`). **No `problem.type` field, no algorithm fields, no metric specs.** Per `config_models.py` docstring: "Orchestration-only. The agent generates BOTH this config AND the per-experiment `@asset` modules ... algorithms / metrics / KPIs are encoded in the generated code, not pinned to enums here." This is a deliberate design choice — adding algorithm-specific fields would violate the agent's flexibility to pivot methodology per-run. Loop modifying `config_models.py` should ONLY add fields that the FIXED scaffold needs (data location, row identity, log destination, seed) — NEVER algorithm-specific config.
- `templates/dagster-experiment/` is a versioned Dagster project. **Verified actual structure (ralph-64)**: top-level dirs `.dg/`, `examples/`, `src/`, `tests/` + files `pyproject.toml`, `README.md`, `CONTRIBUTING.md`, `uv.lock`, `.gitignore`. The `src/pipeline/` package contains: `definitions.py` (2.2K — Dagster `Definitions` factory with auto-discovery), `config_models.py` (1.7K — Pydantic `ExperimentConfig` for the agent's YAML), `resources.py` (2.0K — `ConfigResource`, `MLflowResource`, `make_duckdb_resource`), `_publication_style.py` (3.0K — matplotlib pub-quality defaults), and 2 sub-packages: `assets/` (with `_common/` for fixed infra + `experiment/` for per-run agent-generated `@asset` modules) + `defs/` (currently only empty `__init__.py`, forward-looking). **No `strategies/` directory exists** — earlier PRD claim was wrong (corrected ralph-64). The architecture is auto-discovery: `definitions.py` walks `pipeline.assets.experiment.*` modules at job start; the `config_writer` agent generates these per-run. Workspace contract (verified `definitions.py` docstring): "read config.yaml, write to DuckDB tables, log to MLflow, write final artifacts to results.json + figures/*.png".
- Anti-pattern A1 (SCI overfitting) closed: `tabular_supervised.fit_and_evaluate()` holds out test set BEFORE AutoGluon sees data; default preset `good_quality`.
- Tests in `tests/unit/experiment/` (~150 tests). `InteractiveMLNode` + `JudgeNode` deprecated as of 2026-05-04 cutover but kept for snapshot-deserialization compat.
- Dataset discovery via Exa direct (`web_search_exa` + `web_fetch_exa`); URL verification via `verify_dataset_urls`; SMTP email alerts via `send_dataset_alert` when nothing found.
- **5 sanity functions in `tools/execution/sanity.py`** (verified ralph-43, called by §6.2 ExperimentPhase + AnalysisNode): (a) `sanity_check_results(results: dict) -> list[str]` performs **6 specific checks** with hardcoded thresholds:
  1. "No metrics found in results" (empty metrics dict)
  2. `NaN metric: {method}.{metric_name}` (math.isnan on float)
  3. `Infinite metric: {method}.{metric_name}` (math.isinf)
  4. `Negative metric: {method}.{metric_name} = {value}` — only for bounded set: `{accuracy, f1, f1_macro, f1_weighted, roc_auc, precision, recall}` (7 metrics; **loop must extend this set if breadth mode (Spec 7) introduces new bounded metrics like PR_AUC, MCC, etc.**)
  5. `Suspiciously high accuracy for {method}: {acc:.4f} (possible data leakage)` — threshold `acc > 0.99`, hardcoded (consider tunable per-fixture in §6.15)
  6. `All methods report identical metrics (possible bug)` — only fires when `len(metrics) >= 2`
  Returns `list[str]` not Pydantic — **refactor candidate** for v2.6.0+ (typed `SanityReport(issues: list[SanityIssue])`).
  (b) `verify_plan_alignment(code, plan) -> PlanAlignmentResult` — AST-parses generated code against `ExperimentPlan.baseline_methods + proposed_methods`. (c) `_check_url_reachable(url, timeout=10)` — private helper. (d) `verify_dataset_urls(datasets) -> DatasetVerificationResult`. (e) `send_dataset_alert(...)` async — SMTP email alert (configurable from `.env`).
- Spec 7 Phase 1 wired: `n_design_alternatives` + `k_designs_to_run` config, `design_comparator` + `design_scorer` agents present, but only the highest-scoring design actually executes (no fan-out yet).

**Target state (v2.5.0).**
- Dagster template Stages 3–6 covered (per `2026-05-04-experiment-phase-dagster-template-stages-3-6-plan.md`): classification/regression assets, timeseries assets, multimodal assets, DVC dataset versioning. Each reachable via `config.yaml` `problem.type`.
- Spec 7 Phase 2: `exploration_breadth_enabled` defaults to `true`. `ExperimentDesignerBundleNode` produces N (default 4) designs; `DesignScorerNode` ranks; top K (default 2) designs each get their own Dagster run in parallel; `AnalysisNode` aggregates across runs; thesis-advancing dimension scored.
- `InteractiveMLNode` and `JudgeNode` classes deleted (no more snapshot-deser compat).
- Figures emitted by Dagster assets land in `output/<run-id>/02-experiment/` and are picked up by `LatexCompilerNode` (see §6.7) without re-execution.
- `ExperimentResults.source_code_line` populated via `experiment/line_tracer.py` for every cited number — line-level provenance closed.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.2.T1 | Implement Stage 3 (classification/regression). **CORRECTED ralph-64**: there is NO `strategies/` directory in the template — the actual architecture is auto-discovered `@asset` modules under `pipeline/assets/experiment/*` generated PER-RUN by the `config_writer` agent. Stage 3 work is therefore: (a) extend `config_writer` agent's YAML spec + examples so it can emit richer `@asset` modules for tabular classification/regression (AutoGluon `TabularPredictor`); (b) add canonical examples to `templates/dagster-experiment/examples/` so the agent has reference patterns; (c) add `@asset_check` invariants in `assets/_common/` (test set held out before fit; metrics in expected ranges; etc.). | L |
| 6.2.T2 | Implement Stage 4 (timeseries). **CORRECTED ralph-65**: do NOT add `timeseries.partitioning`/horizon/lag fields to `config_models.py` — that violates the schema's design philosophy. Verified `config_models.py` docstring: "Orchestration-only. ... algorithms / metrics / KPIs are encoded in the generated code, not pinned to enums here. ... Anything an experiment-specific @asset needs (algorithm names, k grids, metrics, AutoGluon presets, custom hyperparams) goes inside the generated asset module — not here." Stage 4 work: (a) extend `config_writer` agent's prompt + add canonical `timeseries_example.py` to `templates/dagster-experiment/examples/` showing AutoGluon `TimeSeriesPredictor` with horizon/lag handling INSIDE the @asset module; (b) optionally add `date_column` field hint to `DatasetConfig` (already exists as `date_column: str | None = None` per ralph-65 verification — no schema change needed). | L |
| 6.2.T3 | Implement Stage 5 (multimodal). **CORRECTED ralph-65**: do NOT add `multimodal.modality_columns` to `config_models.py` — same design-philosophy reason as T2. Modality-column lists encoded in the agent-generated `@asset` module. Stage 5 work: extend `config_writer` agent's prompt + add `multimodal_example.py` to template's `examples/` showing AutoGluon `MultiModalPredictor` setup with modality columns specified inline in the asset code. | L |
| 6.2.T4 | Implement Stage 6 (DVC): add `dvc init` to `template_copier.py` post-copy step, pin HF dataset hashes per run, ensure `dvc pull` reproduces. DVC config lives at workspace root, NOT inside `src/pipeline/` (per DVC convention). | M |
| 6.2.T5 | Spec 7 Phase 2: change `ExperimentPhaseNode.run()` to dispatch K parallel `DagsterRunNode` invocations (one per top-scored design) when `exploration_breadth_enabled=true`. Use `asyncio.gather` (not under DBOS — see `project_dbos_compat`). | L |
| 6.2.T6 | Modify `AnalysisNode` to consume a list of `ExperimentResults` (one per design) and produce a single comparative analysis when in breadth mode. **Per Spec 7 design**: produce a `DesignComparison` artifact with 4 fields: `selected_results: dict[design_id → ExperimentResults]`, `comparison_table` (markdown), `discussion_paragraph` (auto-inserted into paper's Discussion section by §6.3 DraftWriter — verify writer prompt accepts this hand-off), `chosen_design_id` (whose results become primary findings cited throughout). The `discussion_paragraph` is what reviewers will read for the "did you consider X alternative?" challenge. | M |
| 6.2.T7 | Delete `InteractiveMLNode` and `JudgeNode` classes from `experiment/graph.py`. Drop `experiment/specs/ml_engineer.yaml` and `experiment_judge.yaml`. Update `agents.py` registry. **Also delete the orphan `docker/experiment/tcp_server.py` + matching Dockerfile entry** — pre-Dagster TCP-server pattern that paired with `InteractiveMLNode`. **Also delete `experiment/harness.py`** (5-layer enforcement harness for InteractiveMLNode tool surface — verified ralph-46 has 14 FORBIDDEN_IMPORTS + 2 allowlists + TEMPLATE_MAP) **iff Jackson confirms recommended option (a)**: ConfigWriter agent only writes YAML post-Dagster, no executable surface to constrain. Alternative options (b) port to ConfigWriter or (c) keep as defensive infrastructure are also valid — surfaced as OQ-NEW-59. Document state-file incompat + Docker layer change + harness removal in CHANGELOG. | M |
| 6.2.T8 | Wire `experiment/line_tracer.py` output into `ExperimentResults` so every numeric value has `source_code_line: int` populated. Add validator. | S |
| 6.2.T9 | Flip `exploration_breadth_enabled` default to `true` in `config.py` + `configs/default.yaml`. Add `legacy_single_design` escape hatch. | XS |
| 6.2.T10 | Update `tests/unit/experiment/` with: 6 tests for Stages 3–6, 4 tests for breadth-mode design fan-out, 3 tests for line-level provenance population. | L |

**Verification.**
```bash
uv run pytest tests/unit/experiment/ -x -q && \
make test-integration && \
uv run python -m academic_pipeline supervised-run "Predicting hospital readmission using EHR data" --force-experiment --output-dir ./output/_smoke && \
test -s output/_smoke/latest/02-experiment/results.json && \
uv run python -c "import json; r = json.load(open('output/_smoke/latest/02-experiment/results.json')); assert all(m.get('source_code_line') for m in r.get('metrics', [])), 'line provenance missing'"
```

---

### 6.3 Writing subgraph

**Purpose.** Take research artifact + (optional) experiment results and produce a complete paper draft: outline, argument structure, parallel section drafts, abstract, figures (curated from Dagster outputs), citation audit, peer-review pre-pass, formatter output as markdown ready for `LatexCompilerNode`.

**Contract.**
- *Inputs:* `ResearchState`, optional `ExperimentResults`, `PipelineDeps`, `template_target` (IEEEtran or ACL).
- *Outputs:* `WritingState` containing `Outline`, `ArgumentStructure`, list of `Section` (each with markdown body and verified citations), `Abstract`, list of `Figure` (with `source_path` pointing to existing PNG), `CitationAuditReport`, `PeerReviewPrepass`, `FormattedManuscript` (markdown with figure markers and bibtex-key citations).
- *Success criteria:* all sections pass per-node rubric; every numeric claim traceable to research synthesis or `ExperimentResults` (no fabrication); every cited key resolves in bibliography; every figure marker resolves to a real `.png`/`.pdf` under `output/<run-id>/`.

**Current state (end of v2.4.0).**
- 16 nodes in `src/academic_pipeline/writing/graph.py` (~1300 lines).
- 13 YAML specs in `writing/specs/`: `intake`, `literature_strategist`, `structure_architect`, `argument_builder`, `section_writer`, `draft_writer`, `abstract`, `visualization` (now figure curator per recent refactor — **the agent registry key is still `"visualization"` and the file is still `visualization.yaml` with `name: visualization_agent`** per `writing/agents.py` + `writing/specs/visualization.yaml` at HEAD; only the role description changed in commit `27755c7`. Loop must reference the agent as `agents["visualization"]` not `agents["figure_curator"]`), `figure_verifier`, `citation_compliance`, `peer_reviewer`, `revision_coach`, `formatter`.
- Visualization agent recently refactored into figure curator (commit `27755c7`); `available_figures` inventory injected into curator context (`ebb701b`); `LatexCompilerNode` copies Dagster PNGs (commit `2554c98`); `Figure.source_path` field added (`6488c20`); string→`FigureArtifact` boundary conversion (`687ce24`).
- IMRaD structure switch when experiment data present.
- `tests/unit/writing/` covers section drafting, citation compliance, figure resolution.
- **Uncommitted work in flight (per `git status`):** `paper_renderer.py` (+188 lines), `latex_compiler.py` (+98 lines), `writing/graph.py` (+58 lines), `writing/specs/intake.yaml` (+12), `writing/specs/section_writer.yaml` (+25), `writing/specs/structure_architect.yaml` (+33), new tests for ACL templates and caption substitution.

**Target state (v2.5.0).**
- ACL template path supported end-to-end (`template_target: "acl"`); IEEEtran remains default. Template selection threaded from CLI flag through `LatexCompilerNode`.
- StructureArchitect requires per-section "thesis-advancing role" output (Spec 7 Phase 2). Editorial Pre-Integrity rejects sections that do not declare a role.
- Spec 1 Phase 2 (traceability `full` mode) wired: `traceability_mode: full` defaults to `true`. Every numeric value in section bodies carries a trace token resolved at render time. Substitution validator (`traceability/validators.py`) gates editorial. Notes appendix + code appendix auto-emitted in formatter output.
- DraftWriter consumes `Thesis` from research and the cascade verdict from review — no separate revision phase needed once cascade gates pre-integrity.
- All in-flight uncommitted changes landed and tested.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.3.T1 | Land in-flight ACL template work: commit `templates/pandoc/acl/`, `templates/pandoc/acl-header.tex`, updated `latex_compiler.py`, `paper_renderer.py`, `citation_resolver.py`, plus new tests. Existing diff already covers this. | M |
| 6.3.T2 | Add `--template {ieee,acl}` CLI flag in `cli.py`; thread through `Pipeline` SDK + `WritingState`; default `ieee`. | S |
| 6.3.T3 | Modify `structure_architect.yaml` to require `thesis_advancing_role: str` output per section. Update `models/writing.py` `Section` schema. Add `output_validator` rejecting empty roles. | M |
| 6.3.T4 | Modify Pre-Integrity to reject when any `Section.thesis_advancing_role` is empty (Spec 7 Phase 2 enforcement). | S |
| 6.3.T5 | Flip `traceability_mode` default to `"full"` in `config.py` + `configs/default.yaml`. Add `legacy_traceability_off` escape hatch. | XS |
| 6.3.T6 | Wire `traceability/substitution.py` into `paper_renderer.py` so trace tokens (`⟨num:label⟩`) in section bodies resolve to numeric values from `ExperimentResults` at render time. Reject render if any token unresolvable. | L |
| 6.3.T7 | Wire `traceability/validators.py` (point-wise validator) into editorial review pre-pass. Editorial fails if any numeric claim lacks a trace token. | M |
| 6.3.T8 | Auto-emit `traceability/notes_appendix.py` + `code_appendix.py` output as appendix sections in formatter. | M |
| 6.3.T9 | Wire `dialogue.py` helper between `DraftWriter` and `PeerReviewerNode` (Spec 1 full-mode requirement, currently unwired per memory). Max `max_dialogue_turns` (default 3). | M |
| 6.3.T10 | Add 8 unit tests in `tests/unit/writing/test_traceability_full.py`: substitution round-trip, validator gate, dialogue cap, appendix emission, ACL template selection. | M |

**Verification.**
```bash
uv run pytest tests/unit/writing/ tests/unit/runtime/test_paper_renderer.py tests/unit/tools/test_latex_compiler.py -x -q && \
uv run python -c "from academic_pipeline.config import PipelineConfig; c = PipelineConfig(); assert c.traceability_mode == 'full', 'traceability not full'; print('OK')" && \
uv run python -m academic_pipeline write "test topic" --thread-id _smoke --template acl --output-dir ./output/_smoke_acl && \
test -f output/_smoke_acl/latest/03-writing/manuscript.tex
```

---

### 6.4 Review subgraph

**Purpose.** Adversarially review the manuscript draft from multiple angles, produce a single editorial verdict (`accept` / `revise` / `reject`), and route revise/reject back to writing or abort.

**Contract.**
- *Inputs:* `WritingState` (manuscript + figures + citations), `ResearchState.thesis`, `ExperimentResults` (when present), `PipelineDeps`.
- *Outputs:* `ReviewState` with `FieldAnalysis`, list of `ReviewerVerdict` (3 reviewers), `EditorialSynthesis` (decision + revision_directives), `CascadeResult` (cascade Stage A/B/C verdicts), `PointWiseNoveltyReport`.
- *Success criteria:* cascade Stages A and B (numerical grounding, novelty) hard-gate by default. Editorial synthesis enforces cascade verdict (Phase 2). Independent verifier returns PASS for figures.

**Current state (end of v2.4.0).**
- 4 nodes in `src/academic_pipeline/review/graph.py` (~620 lines): `FieldAnalystNode`, `ParallelReviewerNode`, `EditorialSynthesizerNode`, plus optional `PointWiseNoveltyReviewerNode`, `PersonaReviewerPanelNode`, `CascadedReviewNode`.
- **22 review-model classes** in `models/review.py` (verified ralph-49). Two parallel reviewer-output classes coexist for v2.5.0 (loop must keep both during the legacy-flag transition):
  - `PeerReviewReport` (legacy 3 trio: domain/methodology/perspective; behind `legacy_reviewers` flag in Phase 2). Field constraints: `confidence_score: int = Field(ge=1, le=5)` (1-5 range, NOT 0-10 like other rubrics), `strengths` + `weaknesses` each `min_length=1, max_length=5`, `summary_assessment` 150-250 words. **`overall_recommendation: str` is untyped** — opportunity to refactor to `EditorialDecision` enum (4 values: `Accept`/`Minor Revision`/`Major Revision`/`Reject`) which would catch typos at type-check; out of v2.5.0 scope but worth noting.
  - `PersonaReviewOutput` (Spec 5 replacement, default-on in Phase 2; verified iter 34). Carries `PersonaSpec` + `ReviewFinding[]`.
- Notable other classes: `FieldAnalysis`, `EICReview`, `EditorialSynthesis`, `RoadmapItem`/`RevisionRoadmap` (revision routing), `ResponseItem`/`ResponseToReviewers` (author response back to reviewers), `EditorReview`/`ReviewIssue`/`EditorDimensionScore` (EIC scoring). Deletion candidates after Phase 2: none — all classes have active consumers (legacy or new).
- 12 YAML specs in `review/specs/`: `field_analyst`, `domain_reviewer`, `methodology_reviewer`, `perspective_reviewer`, `editorial_synthesizer`, `eic`, `claim_extractor`, `claim_novelty_assessor`, `numerical_claims_auditor`, `senior_gatekeeper_reviewer`, `applied_practitioner_reviewer`, `methodology_purist_reviewer`.
- Phase 1 of Specs 4 (point-wise novelty), 5 (persona), 6 (cascade) shipped. Cascade Stages: A = numerical grounding, B = novelty, C = methodology. Stage A and B short-circuit hard by default; Stage C does not.
- `cascade_aggregation.py` and `cascade_stages.py` implement the cascade. `novelty_aggregation.py` aggregates per-claim novelty scores.
- All four reviewer agents on `anthropic_effort: max`.
- Tests in `tests/unit/review/`.

**Target state (v2.5.0).**
- `pointwise_novelty_enabled`, `persona_reviewers_enabled`, `cascaded_review_enabled` all default `true`.
- `ParallelReviewerNode` defaults to the 3 personas (senior_gatekeeper, applied_practitioner, methodology_purist) instead of the legacy domain/methodology/perspective trio. Legacy 3 behind `legacy_reviewers` flag.
- `EditorialSynthesizerNode` enforces `CascadeResult` verdict: stage A/B fail → editorial decision = `reject`; stage C fail → editorial decision = `revise` with directives derived from cascade. Synthesis no longer free-form.
- Cascade Stage A consumes Spec 1 trace tokens directly; any unresolvable token = stage A fail.
- Per-spec error-code namespaces in postmortems (TRC, COI, NOV, PWN, PRR, CAS, etc.).

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.4.T1 | Flip `pointwise_novelty_enabled`, `persona_reviewers_enabled`, `cascaded_review_enabled` defaults to `true` in `config.py` + `configs/default.yaml`. Add `legacy_reviewers` flag. | XS |
| 6.4.T2 | Modify `ParallelReviewerNode` to dispatch the 3 persona agents by default; legacy trio behind `legacy_reviewers` flag. **Persona-to-legacy mapping** (verified Spec 5 design doc + `review/agents.py` ralph-25): `senior_gatekeeper_reviewer` (thorough × skeptical_gatekeeper × deep_in_field) replaces `perspective_reviewer`; `applied_practitioner_reviewer` (thorough × applied_practitioner × adjacent_field) replaces `domain_reviewer`; `methodology_purist_reviewer` (thorough × domain_purist × deep_in_field) replaces `methodology_reviewer`. **Note**: Spec 5 design doc says "replaces peer_reviewer" but `peer_reviewer` actually lives in `writing/agents.py` (writing-phase pre-pass), NOT in `review/agents.py`. The review-subgraph legacy trio is `domain_reviewer` + `methodology_reviewer` + `perspective_reviewer`. The mapping above corrects the spec-doc inconsistency. Update agent registry. | M |
| 6.4.T3 | Modify `EditorialSynthesizerNode` to accept `CascadeResult` as required input; derive decision from cascade rather than from synthesis prompt. Add unit tests for each of the 8 verdict combinations (3 stages × pass/fail). | L |
| 6.4.T4 | Wire cascade Stage A to consume `traceability/substitution.py` outputs directly. Stage A fails if any token in the manuscript is unresolvable. | M |
| 6.4.T5 | Add `cascade_short_circuit_on_stage_c` flip-to-`true` config + tests for the methodology-as-hard-gate path. Default stays `false` per spec, but make it switchable. | S |
| 6.4.T6 | Update `review/specs/editorial_synthesizer.yaml` prompt: explicit instruction to honor cascade verdict, not override. Add `output_validator` rejecting decisions inconsistent with cascade. | S |
| 6.4.T7 | Add postmortem error codes per cascade stage (CAS-A-NUM, CAS-B-NOV, CAS-C-MTH) and persist to `events.jsonl`. | S |
| 6.4.T8 | Migration path: keep legacy reviewer YAMLs in repo for one release, deprecate in v2.6.0. CHANGELOG note. | XS |
| 6.4.T9 | Add 6 new tests in `tests/unit/review/test_cascade_phase2.py`: stage-A-fail-due-to-unresolvable-token, stage-B-fail-due-to-pointwise-novelty, persona-default-on, legacy-flag-restores-trio, editorial-honors-cascade-reject, editorial-honors-cascade-revise. | M |

**Verification.**
```bash
uv run pytest tests/unit/review/ tests/integration/test_review_graph.py -x -q && \
uv run python -c "from academic_pipeline.config import PipelineConfig; c = PipelineConfig(); assert c.pointwise_novelty_enabled and c.persona_reviewers_enabled and c.cascaded_review_enabled, 'review flags not flipped'; print('OK')"
```

---

### 6.5 Integrity subgraph

**Purpose.** Final integrity gate before finalize: extract claims, scan for plagiarism heuristics, AI-style detection, and (post-Spec-8-Phase-2) PRISMA-trAIce ethics checklist. Loop back to writing if violations found.

**Contract.**
- *Inputs:* `WritingState.manuscript`, `ResearchState.bibliography`, `ResearchState.thesis`, `ExperimentResults`.
- *Outputs:* `IntegrityState` with `ClaimsExtracted`, `PlagiarismReport`, `AIStyleReport`, `EthicsChecklist` (12 items, each `pass`/`fail`/`n/a` + justification), overall `IntegrityVerdict`.
- *Success criteria:* every claim either has a citation or is a novel-contribution claim flagged as such; plagiarism heuristics return no high-similarity hits against bibliography content; ethics checklist has no `fail` items (or all `fail` items have an explicit override directive).

**Current state (end of v2.4.0).**
- 1 composite node in `src/academic_pipeline/integrity/graph.py` (~970 lines) — but with **5-phase internal architecture** (verified ralph-39 from `models/integrity.py:155-205`): `PhaseAReferences`, `PhaseBCitationContext`, `PhaseCData`, `PhaseDOriginality`, `PhaseEClaims` — each producing a `PhaseResult` and contributing to a final `IntegrityReport` (with `blocks_pipeline()` property). PRD prose said "1 node"; actually 1 node orchestrates 5 phases of distinct integrity checks.
- 2 YAML specs in `integrity/specs/`: `integrity_verification`, `compliance_check`.
- **3 legacy heuristic tool functions** in `tools/integrity_tools.py` (verified ralph-40), each `async` returning JSON-string (NOT typed Pydantic — pre-dates `models/integrity.py` pattern; refactoring would be its own task):
  1. `extract_claims(text: str) -> str` — returns JSON `{total_claims, claims}` with claim IDs `CLAIM-001` (zero-padded 3-digit) and 4 claim types: `numerical` / `statistical` / `causal` / `categorical`
  2. `check_plagiarism_heuristic(text: str) -> str` — returns JSON with `verdict: "REVIEW_NEEDED" | "NO_FLAGS"` (2-value literal) plus optional `ai_style_alerts` field
  3. `detect_ai_style_indicators(text: str) -> str` — **SEPARATE function** (not a sub-feature of plagiarism as PRD prose previously implied); `_detect_ai_patterns` is its private helper
- These 3 are called by `IntegrityVerificationNode` for the heuristic-check fast paths; the LLM-driven phases (PhaseA-E) use the structured `models/integrity.py` types instead.
- **Rich type model** at `models/integrity.py` (verified ralph-39): `IntegrityFailureMode`, `IntegrityVerificationOutput`, `ComplianceItemResult`, `ComplianceReport`, `FailureModeResult`, `IntegrityIssue`, `CitationContextIssue`, `DataIssue`, `OriginalityIssue`, `ClaimDistortion`, 5 phase-specific report classes, `PhaseResult`, `IssueCounts`, `IntegrityReport` (with `blocks_pipeline()`), `MaterialPassport` (with provenance + skip-optimization properties).
- `ethics_validator.py` implements the 12-item PRISMA-trAIce checklist (Spec 8 Phase 1, behind `ethics_checklist_enabled` per spec design — flag is currently colocated in the spec validator).
- `novelty_gate.py` lives here architecturally (cross-cutting, called from research subgraph).
- `tests/unit/integrity/`.

**Target state (v2.5.0).**
- `EthicsChecklistNode` is the canonical ethics step (the freeform `EthicsReviewNode` in research is deleted per 6.1.T6). Default-on.
- Integrity loop counter limited by `max_integrity_fix_loops` (already 3) — unchanged.
- Plagiarism heuristics extended to include direct quote detection from `ExperimentResults.dataset_descriptions`.
- AI-style detection emits a per-section score and `ReviseDirective` instead of binary pass/fail.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.5.T1 | Add `EthicsChecklistNode` to `integrity/graph.py` consuming research outputs (RQ + methodology + bibliography + experiment plan + **source_verification artifacts** — per Spec 8 design, source-verification is what surfaces structural COI patterns to the ethics reviewer). Default on. Add `IntegrityState.ethics_checklist: EthicsChecklist \| None = None` field. | M |
| 6.5.T2 | Wire `ethics_validator.py` into the new node; ensure all 12 PRISMA-trAIce items emit a verdict. **The 12 standard item names** (must use these exact strings, per `docs/superpowers/specs/2026-05-03-checklist-ethics-design.md` STANDARD_ITEMS): `human_subjects_disclosed`, `irb_approval_documented`, `informed_consent_documented`, `data_provenance_traced`, `data_use_license_compliant`, `coi_disclosed`, `structural_coi_absent`, `ai_assistance_disclosed`, `reproducibility_artifacts_present`, `phi_pii_absent`, `demographic_representation_addressed`, `potential_misuse_acknowledged`. Validator rejects when any item has `answer=False AND waiver=None` (= blocking), OR when any `answer=True AND len(justification) < 20`. | S |
| 6.5.T3 | Extend `PlagiarismReport` to scan against `ExperimentResults.dataset_descriptions` text. | S |
| 6.5.T4 | Refactor AI-style detection from binary to per-section score + `ReviseDirective`. Update `IntegrityVerdict` schema. **Concrete refactor target** (verified ralph-40): `tools/integrity_tools.py::detect_ai_style_indicators(text: str) -> str` currently returns a JSON string. Change signature to `detect_ai_style_indicators(sections: list[Section]) -> dict[section_name, AIStyleScore]` where `AIStyleScore` is a new Pydantic model with `score: float` (0-10) + `reasons: list[str]` + `revise_directive: ReviseDirective \| None`. Keep the legacy JSON-string variant behind `legacy_ai_style_detection` flag for one release. | M |
| 6.5.T5 | Add 5 unit tests in `tests/unit/integrity/test_ethics_checklist.py`: 12-item coverage, explicit override path, downstream propagation to FinalIntegrity, dataset-descriptions plagiarism path, per-section AI-style score. | M |

**Verification.**
```bash
uv run pytest tests/unit/integrity/ tests/integration/test_integrity_graph.py -x -q && \
uv run python -c "from academic_pipeline.integrity.ethics_validator import PRISMA_TRAICE_ITEMS; assert len(PRISMA_TRAICE_ITEMS) == 12, f'expected 12, got {len(PRISMA_TRAICE_ITEMS)}'; print('OK')"
```

---

### 6.6 Recovery

**Purpose.** Survive the 1h+ wedged-in-recv class of failures observed against the LLM proxy. Detect hangs at four layers (transport, call, process, supervisor); kill cleanly; auto-resume; abort if 3 consecutive resumes fail to advance the events log.

**Contract.**
- *Inputs:* the running pipeline subprocess, `events.jsonl` mtime (proof-of-progress signal — see L4 critical-detail below; **`heartbeat.txt` is NOT used for stall detection** despite earlier PRD prose), configurable thresholds (default `max_idle_s=600` per `WatchdogConfig`, **NOT 75s** as earlier PRD said).
- *Outputs:* on stall — `SIGTERM` to the pipeline's process group, 10s wait, `SIGKILL` if not dead, optional auto-resume via `make resume`. After 3 consecutive failed resumes, abort.
- *Success criteria:* zero observable manual interventions across ≥10 consecutive `make run-experiment` runs against LLM proxy. Watchdog dies cleanly when pipeline finishes successfully. `ProcessLock` files always cleaned.

**Current state (end of v2.4.0).**
- All four layers implemented in `src/academic_pipeline/recovery/`:
  - L1 transport: `transport.py::make_keepalive_async_client(*, timeout=600.0)` injects TCP keepalive socket options into httpx client. **Verified ralph-52** — 3 constants: `_KEEPIDLE_S=60`, `_KEEPINTVL_S=15`, `_KEEPCNT=4` → **detection ≈ 60 + 4×15 = 120s** before OS declares socket dead. Per-OS branching: macOS 10.15+ (TCP_KEEPALIVE / TCP_KEEPINTVL / TCP_KEEPCNT), Linux (TCP_KEEPIDLE / TCP_KEEPINTVL / TCP_KEEPCNT), Windows (SO_KEEPALIVE only, slower OS-default probes). Default httpx `Timeout(connect=10.0, read=600.0, write=600.0, pool=10.0)`. `Provider` constructors monkey-patched at import time (re-entrancy-safe via `__keepalive_patched__` sentinel). Single shared client cached via `_get_shared_keepalive_client()`. **Background**: macOS default keepidle is 7,200,000 ms (2 hours); without these socket options, `recv()` blocks indefinitely on a silently-dropped TCP connection. Pattern adapted from shigechika/mcp-stdio PR #34 (Apr 2026), which solves the same class of bug for MCP SSE streams.
  - L2 call: `bounded_run.py::bounded_agent_run(agent, context, *, timeout_s=900.0, **kwargs)` wraps `agent.run()` with `asyncio.wait_for`. **TWO timeout paths exist (verified ralph-68)**: (a) direct `bounded_agent_run` call uses default 900s (15-min cap, e.g. evaluator call sites that need long-running judge runs); (b) every `traced_agent_run` call OVERRIDES to `_AGENT_RUN_TIMEOUT_S = 480.0` (`runtime/trace_logger.py:21`) so the effective cap on the vast majority of agent runs in the pipeline is **8 minutes**, NOT 15. **CRITICAL ORDERING INVARIANT**: traced_agent_run cap (480s) MUST be < watchdog `max_idle_s` (600s). Inverting this is a known regression (run-0504-1802_ec44 post-mortem): when agent timeout > watchdog timeout, the watchdog SIGKILLs the process group at 600s instead of letting bounded_run raise `AgentTimeoutError` → snapshot recorded as `error` → auto-resume picks up cleanly. With the OLD 900s trace-logger cap, watchdog killed at 600s instead, wasting 5 extra minutes per cycle and corrupting in-flight snapshots. **Loop MUST keep `_AGENT_RUN_TIMEOUT_S < WatchdogConfig.max_idle_s` if either is changed.** Generic: `Agent[_TDeps, _TOutput] → AgentRunResult[_TOutput]` preserves type safety end-to-end. Raises `AgentTimeoutError(RuntimeError)` on timeout. Wired into `runtime/trace_logger.traced_agent_run` and the 3 evaluator call sites. **Critical scope clarification (verified ralph-52 docstring)**: L2 catches the LEGITIMATE-slow case (LLM is actually thinking for >15 min). It does **NOT** save us from blocked-in-`recv()` stalls — `asyncio.wait_for` cannot preempt a sync syscall blocked in the kernel (verified via socketpair test). Stuck-in-recv stalls are caught by **L1** (TCP keepalive at OS level) and **L4** (watchdog at process level); L2 alone is insufficient. Loop must understand this division of responsibility before reasoning about hang-recovery completeness.
  - L3 process: `heartbeat.py::Heartbeat(path, interval_s=30.0)` daemon-thread context manager emits to `heartbeat.txt` every 30s (NOT an asyncio task — would starve when event loop is blocked, e.g. inside synchronous `socket.recv` in an SDK; verified comment cites Prefect issue #21184 + PR #21276 as precedent for the bug). Atomic write via `.tmp` + POSIX rename — watchdog reading `stat().mtime` never sees half-written file. Thread name format: `pipeline-heartbeat-{path.name}` (discoverable in `ps` / `top` output).
  - L4 supervisor: `watchdog.py::WatchdogConfig` + `run_watchdog`; `supervisor.py::supervised_run` spawns pipeline + watchdog as sibling subprocesses each in its own process group via `os.setsid`. **Verified WatchdogConfig defaults (ralph-53)**: `max_idle_s=600` (**NOT 75s** as PRD prose previously said — 75s was the original default but was changed in v2.4.x after observing false-positive kills at `age_s=76.6` in `run-0504-1802_ec44`. SourceVerificationNode + BibliographyNode legitimately spend 60-120s between events.jsonl writes when looping over S2/CrossRef/Retraction-Watch or batching Exa neural searches. The watchdog's purpose is to catch HOURS-long LLM proxy SSE wedges, not minutes-long-but-progressing nodes. 600s = 10min headroom). `poll_interval_s=30` (watchdog polls every 30s). `max_strikes=3`. `_GRACEFUL_KILL_S=10` (10s SIGTERM-before-SIGKILL). `_RESUME_PID_TIMEOUT_S=60` (wait 60s for resumed pipeline to write its PID file). `process_state.py::ProcessLock(persistence_dir, thread_id)` writes **TWO files per run** (verified ralph-51): `<persistence_dir>/<thread_id>.pid` AND `<persistence_dir>/<thread_id>.pgid`. **Graceful fallback** when `os.getpgid(0)` raises `OSError` (rare — only on systems without process groups): writes own PID as PGID, watchdog degrades to single-process kill (`os.kill` instead of `os.killpg`) which still works for the common case. Cleanup uses `missing_ok=True` so partial-failure exit doesn't double-fault. Atomic writes via `.tmp` + POSIX rename throughout.

  **CRITICAL: heartbeat.txt is NOT used for stall detection** (verified ralph-53 from `watchdog.py:9-15` docstring): "The heartbeat is written by a daemon thread which keeps ticking even when the main code is hung in an `await` (e.g. PydanticAI/Anthropic SDK waiting for SSE chunks that never arrive after the proxy drops the stream). Trusting heartbeat for stalls masked this exact failure mode in run-0504-1212_cf0d (1h41m wedged with fresh heartbeat). Events.jsonl is the only signal that proves the pipeline is making real progress." PRD prose previously implied the watchdog polls both heartbeat.txt AND events.jsonl mtime — only events.jsonl is the proof-of-progress signal. The heartbeat exists to prove the daemon thread is alive, NOT to prove the pipeline is progressing. **Loop must NOT add heartbeat.txt to stall-detection logic** — that was the bug being avoided.
- CLI: `python -m academic_pipeline supervised-run`, `watchdog`, `supervised-resume`. Makefile targets: `run-experiment`, `run-experiment-debug`, `watchdog`, `resume`, `resume-bare`.
- 3-strikes escalation in watchdog. Stale `output/latest` symlinks rejected via `min_mtime`. Watchdog's own events excluded from strike counter. PGID file unlinked before resume to avoid stale-process-group races. Dead-watchdog detection.
- **Recursive-supervisor pattern** (verified ralph-42 from `recovery/supervisor.py:1-17` docstring): when watchdog SIGKILLs the pipeline, the original supervisor exits with the pipeline's signal exit code (e.g. -15). The watchdog's auto-resume invokes `make resume` which routes through `supervised-resume` → spawns a FRESH `supervised_run` with its own FRESH watchdog. The resumed pipeline is NOT orphaned. Operator finds it via the latest pgid file or `output/<thread_id>/events.jsonl`. **This means a single user-visible run can span multiple supervisor processes across the recovery lifecycle** — important for log-aggregation and dashboard renderers (must not assume one supervisor process per `run_id`).
- **Verified constants** at `recovery/supervisor.py:34-35`:
  - `_THREAD_ID_TIMEOUT_S = 60` — supervisor waits up to 60s for the pipeline to write its first events.jsonl line before assuming the pipeline failed at boot
  - `_WATCHDOG_GRACEFUL_S = 10` — graceful-shutdown window after `SIGTERM` before escalating to `SIGKILL` (matches the L4 watchdog 10s wait)
- **`_strip_flag(args, *flags)` helper** at `recovery/supervisor.py:38` — removes user-provided `--thread-id` / `--auto-resume` / etc. from argv before re-spawning, to prevent typer's "last wins" rule from silently overwriting the supervisor's own values. Loop must use this when adding new supervisor-managed flags.
- Tests: `tests/unit/recovery/`, `tests/integration/test_hang_recovery_e2e.py`.
- Behind the `2026-05-01-hang-recovery-design.md` spec; full plan at `2026-05-01-hang-recovery.md` (82KB).

**Target state (v2.5.0).**
- No structural changes — the 4-layer system is already complete and stable. Hardening only.
- Add a `--max-recoveries` CLI flag (currently hard-coded to 3 in watchdog) for power-user override.
- Surface per-layer recovery metrics in `events.jsonl` (which layer fired, how often per run).
- Document the recovery system in `docs/architecture/recovery.md` (currently only in the spec/plan).

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.6.T1 | Add `--max-recoveries N` flag to `cli.py::watchdog` and `cli.py::supervised_run`. Default 3, configurable per invocation. | XS |
| 6.6.T2 | Emit `recovery_event` records to `events.jsonl` (`{layer: 1\|2\|3\|4, action: "kill"\|"resume"\|"abort", ts, reason}`). Update `runtime/events.py` and dashboard renderer. | S |
| 6.6.T3 | Write `docs/architecture/recovery.md` (≤200 lines): one-paragraph per layer, file pointers, failure modes covered, how to debug a recovery loop. | S |
| 6.6.T4 | Add 3 integration tests in `tests/integration/test_hang_recovery_e2e.py`: max-recoveries flag honored, `recovery_event` lines present in events.jsonl after a forced kill, dashboard shows recovery count. | M |

**Verification.**
```bash
uv run pytest tests/unit/recovery/ tests/integration/test_hang_recovery_e2e.py -x -q && \
test -f docs/architecture/recovery.md && \
uv run python -m academic_pipeline watchdog --help | grep -- '--max-recoveries'
```

---

### 6.7 Rendering

**Purpose.** Compile the formatted markdown manuscript + bibtex + figures into a journal-format PDF (IEEEtran or ACL) via pandoc + tectonic. Survive figure-source-of-truth pivot (figures-via-Dagster), citation-key-style normalization, longtable-in-2-column layouts, and DOI verification at build time.

**Contract.**
- *Inputs:* manuscript markdown with figure markers and bibtex-key citations, bibtex file, list of `Figure` artifacts (with `source_path` resolving to a real `.png`/`.pdf`), `template_target` (`ieee`/`acl`), `authors.yaml`.
- *Outputs:* `manuscript.pdf` under `output/<run-id>/03-writing/`. Compilation log captured. DOI-verification report.
- *Success criteria:* tectonic exit 0; PDF non-empty; every citation in PDF resolves; every figure renders; DOI gate passes (every cited DOI verified via CrossRef).

**Current state (end of v2.4.0, including in-flight uncommitted).**
- `src/academic_pipeline/runtime/paper_renderer.py` — orchestrates render. **Verified ralph-59: 2 public renderers**: (a) `render_markdown(draft: PaperDraft, figure_package: FigurePackage | None = None) -> str` emits pandoc-compatible markdown with YAML frontmatter (`title`, `author` semicolon-separated `"name, affiliation"` per author, `abstract: |` folded literal, `numbersections: true`); (b) `render_latex(draft, bib_source="") -> str` emits direct LaTeX. **Production pandoc config** (verified docstring lines 63-67): `--natbib` + **`acl_natbib.bst`** bibliography style file → renders `[@bibkey]` as parenthetical author-year + auto-generates references section. **`[FIGURE: N]` marker contract**: markers WITH a matching figure → `![<caption>](figures/figure_NN.png)`; markers WITHOUT match are **LEFT IN PLACE** so the gap is visible to the author (NOT silent-skipped — explicit anti-pattern). **Abstract is YAML frontmatter, NOT a section**: heading `"abstract"` is skipped case-insensitively in the section loop. **`ref_map` is 1-indexed** (`for i, ref in enumerate(draft.references, 1)`) — important when wiring numbered-reference render paths. Uncommitted: `_substitute_figure_markers` prefers `Figure.source_path` over re-execution.
- `src/academic_pipeline/runtime/citation_resolver.py` — bibliography-aware bracket-token resolver (a `[token]` is a citation iff `token` is a key in the bibliography). **Verified ralph-58: 3 resolution functions, NOT 1**: (a) `resolve_citations_to_cite_commands(text, ref_map: dict[str, int]) -> str` — emits LaTeX `\cite{bibkey}` (natbib); (b) `resolve_citations_to_numbers(text, ref_map) -> str` — emits `[1, 2, 3]` numbered references; (c) `resolve_citations_to_pandoc(text, ref_map) -> str` — emits pandoc citeproc `[@bibkey]` syntax (multi-key uses **semicolon**: `[@a; @b]`, not comma). Loop must pick the right function for the render path. Plus 1 heuristic helper: `extract_cite_tokens(text) -> list[str]` filters by year-bearing regex `\d{4}` for downstream-tooling discovery (different role from the 3 resolvers). **Adjacency merging** (`[a][b]` → `[a,b]`) requires BOTH keys present in `ref_map` — mixed known/unknown leaves both alone. **Unknown brackets pass through unchanged** — preserves clinical trial IDs (`[NCT12345]`), CVE numbers (`[CVE-...]`), equation labels (`[IV]`), etc. without touching them. Uncommitted: pandoc integration tests added.
- `src/academic_pipeline/tools/rendering/latex_compiler.py` — pandoc + tectonic invocation. **Verified ralph-60 exact pandoc command** (the production ACL render path):
  ```bash
  pandoc paper.md -o paper.pdf \
    --pdf-engine=tectonic \
    -V documentclass=article -V classoption=11pt \
    --number-sections \
    --include-in-header=acl-header.tex \
    --lua-filter=longtable-to-table-star.lua \
    [--natbib --bibliography=references.bib  ← CONDITIONAL: only when bib_source is truthy]
  ```
  **CRITICAL ANTI-PATTERN** (verified `latex_compiler.py:196-201` comment): the loop **MUST NOT** add `--biblatex` or `-V biblio-style`. acl.sty calls `\bibliographystyle{acl_natbib}` internally at `acl.sty:195`; a second `\bibstyle` crashes bibtex with `"Illegal, another \bibstyle command"`. Adding what looks like a "missing flag" would silently break every ACL build. **Conditional bib flags**: `--natbib --bibliography=...` only added when `bib_source` is truthy — without this guard, pandoc emits `\bibliography{references}` that tectonic fails on (no .bib file present). **Per-build asset copy** via `_copy_acl_assets(output_dir)` because pandoc resolves `--include-in-header` and `--lua-filter` relative to its cwd. Missing assets raise with `"see templates/pandoc/acl/README.md"` pointer. **2 compile paths**: `_run_tectonic(working_dir)` (direct tectonic for non-ACL) + `compile_pdf_pandoc(...)` (pandoc + tectonic for ACL — production). `apply_traceability_substitutions` runs **before** pandoc — substitutes `⟨num:label⟩` tokens and appends Notes/Code appendices. Uncommitted: copies Dagster PNGs from `02-experiment/` into the writing build dir; longtable-to-table\* Lua filter.
- `templates/pandoc/`:
  - `acl-header.tex` (uncommitted)
  - `acl/` (uncommitted)
  - `longtable-to-table-star.lua` (committed)
- `templates/dagster-experiment/src/pipeline/_publication_style.py` re-exported as `apply_pub_style` from package root (commit `7a4fe6a`).
- IEEEtran switched to `journal+onecolumn` so longtable compiles (`0778687`).
- Tests: `tests/unit/runtime/test_paper_renderer.py`, `tests/unit/tools/test_latex_compiler.py`, plus uncommitted `tests/unit/runtime/test_citation_resolver_pandoc.py`, `tests/unit/runtime/test_paper_renderer_captions.py`.

**Target state (v2.5.0).**
- All in-flight uncommitted rendering work landed and tested.
- ACL template path proven end-to-end against a real ACL `.cls` file in `templates/pandoc/acl/`.
- DOI CrossRef build gate: at compile time, every DOI in the bibtex is checked against CrossRef; failures abort the build with a clear error. Plan at `2026-05-05-doi-crossref-build-gate.md`.
- `authors.yaml` required at compile time; missing file aborts build with a clear error. Plan at `2026-05-05-authors-yaml-required.md`.
- Title-12-words constraint enforced at formatter boundary (rejects > 12 words). Plan at `2026-05-05-title-12-words-constraint.md`.
- Figures-via-Dagster fully cuts over: `figure_executor.py` sandbox runner deleted (already done in commit `8150844`); writing graph never re-executes figure scripts.
- Publication-quality matplotlib defaults applied via `apply_pub_style` per plan `2026-05-05-publication-quality-matplotlib.md`.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.7.T1 | Land in-flight changes: commit `templates/pandoc/acl/`, `acl-header.tex`, updated `paper_renderer.py`, `citation_resolver.py`, `latex_compiler.py`, new tests. Bundles with 6.3.T1. | M |
| 6.7.T2 | Implement DOI CrossRef build gate per `2026-05-05-doi-crossref-build-gate.md`: `latex_compiler.py` invokes `tools/bibliography/doi.py::verify_dois_in_bibtex` before tectonic. Fail build on any unverified DOI; emit `events.jsonl` `doi_gate_failure` record. | M |
| 6.7.T3 | Implement `authors.yaml` required gate per `2026-05-05-authors-yaml-required.md`: `LatexCompilerNode` reads `authors.yaml` from project root or run dir; failure to find aborts with `MISSING_AUTHORS_YAML` error code. | S |
| 6.7.T4 | Implement title 12-word constraint per `2026-05-05-title-12-words-constraint.md`: `formatter` agent's `output_validator` rejects manuscripts with `title.split() > 12`; one revision attempt allowed. | S |
| 6.7.T5 | Implement publication-quality matplotlib per `2026-05-05-publication-quality-matplotlib.md`: `apply_pub_style()` called in every Dagster figure asset; consistent fonts, sizes, DPI, color palette. | M |
| 6.7.T6 | Add ACL e2e smoke test in `tests/integration/test_pipeline_graph.py`: render against a stub ACL template, assert PDF produced. | M |
| 6.7.T7 | Update `docs/architecture/rendering.md` (or create) with: figures-via-Dagster flow, template selection, DOI gate, authors.yaml contract, title constraint, longtable filter. | S |
| 6.7.T8 | **Cleanup orphan:** delete `scripts/rerender_latest.py` (currently broken — imports the deleted `tools.rendering.figure_executor` from commit `8150844`). If a re-render utility is still needed, replace with a thin wrapper around `LatexCompilerNode.run()` that targets `output/latest/03-writing/`. | XS |
| 6.7.T9 | **Add ACL anthology citation style.** Verified ralph-30: `tools/bibliography/citations.py::STYLE_DISPATCH` (line 152) covers exactly 5 styles: `"APA7"`, `"Chicago"`, `"MLA"`, `"IEEE"`, `"Vancouver"` (literal strings). ACL anthology format is NOT in the dispatch. Task: add `_format_acl()` formatter, register in `STYLE_DISPATCH`, extend `validate_citation()` for ACL-specific rules, add unit tests in `tests/unit/tools/test_citations.py`. ACL template (§6.7.T1) selects via `template_target == "acl"` → `format_citation(meta, style="ACL")`. | M |

**Verification.**
```bash
uv run pytest tests/unit/runtime/test_paper_renderer.py tests/unit/runtime/test_citation_resolver_pandoc.py tests/unit/runtime/test_paper_renderer_captions.py tests/unit/tools/test_latex_compiler.py tests/unit/tools/test_citations.py -x -q && \
test ! -f scripts/rerender_latest.py || (uv run python -c "import importlib.util; spec = importlib.util.spec_from_file_location('r', 'scripts/rerender_latest.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)") && \
uv run python -m academic_pipeline run "test topic" --thread-id _smoke_render --template ieee --output-dir ./output/_smoke_render && \
test -s output/_smoke_render/latest/03-writing/manuscript.pdf
```

---

### 6.8 Dashboard + Events

**Purpose.** `events.jsonl` is the single source of truth for pipeline progress. The dashboard is a pure renderer over it. Operators read the dashboard live (`--watch`) or via the snapshot under `output/<run-id>/dashboard.txt`. Autonomous loops read events.jsonl programmatically to know what completed and what failed.

**Contract.**
- *Inputs:* `output/<run-id>/events.jsonl` (append-only, line-delimited JSON), each line a typed event (`pipeline_start`, `stage_change`, `node_complete`, `node_error`, `pipeline_complete`, `pipeline_error`, `heartbeat`, plus future `recovery_event`, `doi_gate_failure`, `cascade_verdict`).
- *Outputs:* `output/<run-id>/dashboard.txt` (snapshot, written on every node completion), live Rich renderer via `python -m academic_pipeline dashboard --watch --latest`.
- *Success criteria:* every pipeline state transition appears in events.jsonl; dashboard accurately renders current node, stage progress, error counts, recovery counts; no dropped events under crash/resume.

**Current state (end of v2.4.0).**
- `src/academic_pipeline/runtime/dashboard.py` — pure renderer (`read_events`, `apply_event`, `derive_state`, `render`). **Verified ralph-61: 4 frozen dataclasses + 5 functions**:
  - `NodeInfo(name, scope: "outer"|"subgraph", duration_s, status: "completed"|"error", error)` — one node
  - `StageInfo(name, nodes: tuple[NodeInfo, ...], started_at, ended_at, status: "pending"|"running"|"completed"|"error")` — one stage
  - `WatchdogAction(action: "killing"|"killed"|"resuming"|"resumed"|"aborted", ts, pgid, age_s, strike, reason, killed_cleanly)` — one watchdog action (5 action types match the events.jsonl watchdog set verified iter 27-28)
  - `RunState(run_id, topic, started_at, resumed_count, pipeline_status, pipeline_error, current_stage, stages: Mapping[str, StageInfo], watchdog_actions: tuple[WatchdogAction, ...] = ())` + `RunState.empty()` classmethod for tests
  - Pure-functional pipeline: `read_events(path) → list[dict]` (NEVER raises, returns empty list on missing file — design philosophy: "the dashboard is a derived view, not a system of record"), `apply_event(state, event) → RunState` (returns NEW state, immutable), `derive_state(events) → RunState` (fold over events), `render(state) → Panel` (Rich terminal panel), `latest_run_dir(output_root) → Path | None`.
- `src/academic_pipeline/runtime/events.py` — event-type definitions.
- `output/<run-id>/events.jsonl` written by graph nodes via `events.py::emit`.
- CLI: `python -m academic_pipeline dashboard --latest`, `--watch`, `<run-id>`.
- Tests: `tests/unit/runtime/test_dashboard.py`, `tests/integration/test_dashboard_e2e.py`.
- React dashboard exists on main (per `project_dashboard_v1` memory) but works only at v1 — needs v2 redesign with node progress, metrics, inline artifacts.

**Target state (v2.5.0).**
- `events.jsonl` schema extended for: `recovery_event` (per §6.6.T2), `doi_gate_failure` (per §6.7.T2), `cascade_verdict` (per §6.4), `novelty_gate_verdict`, `ethics_checklist_result`.
- Dashboard renders: cascade verdict per stage, novelty gate score, ethics checklist pass count, recovery count.
- React dashboard v2: node progress bars, per-node metrics (token count, duration, retries), inline figure preview, link to MLflow run.
- Schema versioning: `events.jsonl` first line = `{"event_type": "schema_version", "version": "2.5.0"}`. Renderer rejects unknown versions.
- `dashboard.txt` snapshot written on every event (not only node completion) — bound to a 250ms throttle to avoid disk thrash.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.8.T1 | Add new event types in `runtime/events.py`: `recovery_event`, `doi_gate_failure`, `cascade_verdict`, `novelty_gate_verdict`, `ethics_checklist_result`. Define typed `pydantic.BaseModel` per type. | S |
| 6.8.T2 | Update `runtime/dashboard.py::apply_event` + `render` to handle new event types. Add per-stage cascade rendering and novelty score panel. | M |
| 6.8.T3 | Add `schema_version` first-line emission in `events.py::Pipeline.start`. Renderer reads first line and rejects mismatched versions with a clear error. | S |
| 6.8.T4 | Throttle `dashboard.txt` writes to ≤4 Hz. **CRITICAL — DO NOT use `runtime/throttle.py`** (verified ralph-74): that module is a PydanticAI `Hooks` capability for `before_model_request` throttling — wrong API surface, wrong semantics (sleep before AGENT request, not file-write debounce). Add a NEW small utility in `runtime/dashboard.py` itself: time-based debounce that tracks `last_write_ts` and skips writes within `min_interval_s = 0.25` (4 Hz). PRD-prose drift now corrected. Add unit test verifying snapshot debounce. | S |
| 6.8.T5 | Update React dashboard v2: per-node progress bar, token/duration/retry per node, inline figure preview from `output/<run-id>/02-experiment/figures/`. Component design referenced from `project_dashboard_v1` memory. | L |
| 6.8.T6 | Add 4 unit tests in `tests/unit/runtime/test_dashboard.py`: schema version mismatch rejection, new event types render, throttle debounce, recovery count surfaces. | M |

**Verification.**
```bash
uv run pytest tests/unit/runtime/test_dashboard.py tests/integration/test_dashboard_e2e.py -x -q && \
uv run python -m academic_pipeline dashboard --latest --output-dir ./output | head -20 && \
test "$(head -1 output/latest/events.jsonl | python -c 'import sys,json; print(json.loads(sys.stdin.read())[\"event_type\"])')" = "schema_version"
```

---

### 6.9 Persistence + AgentCache

**Purpose.** Crash resilience. Pipeline state must survive process death; agent message history must survive between judge/improvement loop iterations and across crash/resume; `make resume THREAD_ID=X` must restore the exact node mid-pipeline with no work re-typed and no agent dialogue lost.

**Contract.**
- *Inputs:* `PipelineState` updates (graph node transitions), `ModelMessage` lists from PydanticAI agents.
- *Outputs:* `.pipeline_runs/<thread-id>_state.json` (graph state, serialized via `pydantic.TypeAdapter`); `.pipeline_runs/<thread-id>_agent_cache.json` (PydanticAI message history via `ModelMessagesTypeAdapter`).
- *Success criteria:* `make resume THREAD_ID=<crashed-run>` produces identical downstream output to a fresh run (modulo nondeterminism inherent to the model). `_reset_crashed_snapshots()` correctly distinguishes crashed-mid-node from completed-node states.

**Current state (end of v2.4.0).**
- `src/academic_pipeline/persistence.py` (verified ralph-73, **373 lines**) — `SqliteStatePersistence(BaseStatePersistence[StateT, RunEndT])` for state files. **Two-table SQLite schema** (verified `_SCHEMA_SQL` at lines 38-58):
  1. **`snapshots` table** — per-graph-node snapshots. Columns: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `run_id TEXT`, `snapshot_id TEXT`, `kind TEXT` (`'end'` | `'node'`), `status TEXT DEFAULT 'created'`, `data_json TEXT`, `duration REAL`, `start_ts TEXT`, `created_at TEXT DEFAULT (datetime('now'))`. **NO UNIQUE constraint on (run_id, snapshot_id)** — Python-level dedup via `snapshot_node_if_new` reads `load_all()` and checks. Loop must keep this dedup check or duplicate snapshots arise on idempotent retries. Two indexes: `idx_snapshots_run` on `run_id`, `idx_snapshots_sid` on `(run_id, snapshot_id)`.
  2. **`pipeline_state` table** — top-level `PipelineState` JSON, separate from per-node snapshots. Columns: `run_id TEXT PRIMARY KEY`, `state_json TEXT`, `updated_at TEXT DEFAULT (datetime('now'))`. UPSERT semantics via `INSERT...ON CONFLICT(run_id) DO UPDATE`. Loop must NOT collapse `pipeline_state` into `snapshots` — pipeline-level state has different lifecycle than graph-node snapshots (pipeline state mutates between nodes; graph snapshots are append-only).
- **WAL journal mode** (verified `__post_init__` line 76): `PRAGMA journal_mode=WAL` enables concurrent reads + writes. Loop must NOT change to default `DELETE` mode — watchdog reads via separate connection while pipeline writes.
- **Connection-per-call pattern** — every sync method opens + closes its own `sqlite3.connect(str(self.db_path))`. NO connection pool. Simple but creates overhead on hot paths. Loop introducing a long-lived connection MUST handle thread safety (multi-threaded sqlite needs `check_same_thread=False` + serialized access).
- **Snapshot-status state machine** (verified `load_next` + `record_run` + `reset_crashed_snapshots`):
  - `created` → loaded by `load_next()` → `pending`
  - `pending` → entered by `record_run()` async context manager → `running`
  - `running` → on context exit → `success` (no exception) or `error` (exception, then re-raised)
  - `running` and `error` → reset by `reset_crashed_snapshots()` → `created` (graceful resume; PRD prose says only `running` was reset, but verified ALSO resets `error`-status — important for idempotent retry of failed nodes)
- **CRITICAL TypeAdapter timing invariant** (verified `_insert_snapshot:178` + `_load_all_sync:200` + `_reset_crashed_sync:349-370`): `self._snapshots_type_adapter` MUST be set via `set_types(state_type, run_end_type)` before `_insert_snapshot` or `_load_all_sync`. Both raise `assert ... is not None`. **`_reset_crashed_sync` has GRACEFUL FALLBACK**: when called BEFORE `graph.iter_from_persistence` sets types (the legitimate resume-time case), it patches `data_json` directly via JSON manipulation (lines 352-370) — strips `duration` + `start_ts`, sets `status='created'`. Loop MUST keep this fallback or resume crashes when invoked before graph init.
- **JSON list-of-one trick** (verified `_insert_snapshot:179-185`): `dump_json([snapshot])` then strip outer `[`/`]` for single-row storage. `_load_all_sync` joins all rows back as `"[" + ",".join(...) + "]"` for batch validation. This is because `build_snapshot_list_type_adapter` is a LIST adapter — there's no per-item adapter exposed. Loop must NOT try to add `validate_python` per-row or it crashes the type-adapter API.
- **`_rewrite_data_json` after every status update** (verified `_update_status_sync:245`): re-loads all snapshots, applies current DB metadata (status/duration/start_ts) to the matching one, dumps back to JSON, UPDATEs the single row's `data_json`. Without this, resume sees stale status. Loop modifying status update path MUST keep the rewrite — the data_json is the authoritative source on resume, NOT the status column directly.
- **Async/sync split** — every public method `await _graph_utils.run_in_executor(self._foo_sync, ...)` to keep the asyncio event loop responsive (sqlite3 is blocking sync). Loop adding new methods MUST follow this pattern.
- **8 sync helpers** (verified module structure): `_insert_snapshot`, `_load_all_sync`, `_update_status_sync`, `_rewrite_data_json`, `_save_pipeline_state_sync`, `_load_pipeline_state_sync`, `_can_resume_sync`, `_reset_crashed_sync`. All 8 follow the connection-per-call + try/finally close pattern. Loop adding helpers MUST follow this exact pattern; deviating leaks file descriptors.
- `src/academic_pipeline/tools/agent_cache.py` — `AgentMessageCache(cache_dir: str, agent_name: str)` for PydanticAI message history. **Verified API surface** (ralph-50): 4 methods — `save(messages_json: bytes)`, `load() -> list[ModelMessage] | None`, `clear()`, `exists() -> bool`. Cache path: `<cache_dir>/<agent_name>.json`. Uses `ModelMessagesTypeAdapter.validate_json` for deserialization. **Corrupt cache handling**: `load()` catches Exception, logs warning, returns `None` (silently degrades to "no cache" — does NOT raise). Loop must understand: a corrupt cache file means the next run starts fresh, doesn't crash. Wired into ML engineer judge loop per `2026-04-30-agent-message-cache-design.md`.
- `_reset_crashed_snapshots()` recovers from interrupted node state. **Verified ralph-73**: resets BOTH `'running'` AND `'error'` statuses to `'created'` (NOT just `'running'` as PRD prose previously implied) AND clears `duration` + `start_ts` columns. SQL: `UPDATE snapshots SET status = 'created', duration = NULL, start_ts = NULL WHERE run_id = ? AND status IN ('running', 'error')`. The dual reset is intentional — `'error'` snapshots from a previous run with a transient failure (e.g. proxy hang killed at 600s) need to be retryable on resume; otherwise the resume sees `'error'` and short-circuits.
- `pydantic.TypeAdapter`-based serialization throughout — no custom JSON encoders.
- SQLite checkpointer at `~/.academic_pipeline/checkpoints.db` (default backend).
- Tests: `tests/unit/test_persistence.py`, `tests/integration/test_resume.py` (17.4KB — substantial coverage).
- **State-file compat caveat:** files from before 2026-05-02 are incompatible (`cross_model_*` → `independent_verifier_*` rename). Documented in CLAUDE.md.
- **Subgraph resume gotcha:** `pydantic-graph iter_from_persistence` ignores state arg; callers must capture `run.state` (per `project_subgraph_resume_gotcha`).

**Target state (v2.5.0).**
- State-file schema versioning. Each state file carries `{"_schema_version": "2.5.0", ...}`. Resume rejects mismatched versions with a clear error and links to migration notes.
- `make resume` works from any node in any subgraph after any of the four recovery layers fires.
- `AgentMessageCache` extended to all agents that have multi-turn dialogue: ml_engineer (already done), draft_writer↔peer_reviewer dialogue (Spec 1 full mode), config_writer→Dagster failure feedback loop.
- One unified `tools/agent_cache.py::for_agent(agent_name, thread_id)` factory; per-agent cache files at `.pipeline_runs/<thread-id>_<agent>_cache.json`.
- Drop the `cross_model_*` back-compat shim entirely (already deleted in 2.4.0); add cleanup script to nuke pre-2.5.0 state files.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.9.T1 | Add `_schema_version` field to `PipelineState`. `SqliteStatePersistence.load` rejects mismatched versions with `IncompatibleStateError` and points to migration notes. | S |
| 6.9.T2 | **Reconsider** — current `AgentMessageCache(cache_dir, agent_name)` API may already provide per-agent + per-thread isolation when called with `cache_dir=.pipeline_runs/<thread_id>/` (verified ralph-50). The proposed `for_agent(agent_name, thread_id)` factory is sugar over the existing constructor. **Decision needed**: (a) keep current API + add convenience `AgentMessageCache.for_agent(thread_id, agent_name)` classmethod that just calls `AgentMessageCache(f".pipeline_runs/{thread_id}/", agent_name)`; (b) leave as-is — current API is clear enough; (c) full rename refactor. **Recommendation: (a)** — minimal API change, supports the §6.9.T3/T4 dialogue + config_writer cache wiring without refactor cost. Drop the "factory pattern" framing. | S |
| 6.9.T3 | Wire `AgentMessageCache.for_agent("draft_writer_dialogue", thread_id)` into the writer↔reviewer dialogue helper (bundled with 6.3.T9). | S |
| 6.9.T4 | Wire `AgentMessageCache.for_agent("config_writer", thread_id)` so config_writer can iterate on Dagster failure feedback without losing context. | S |
| 6.9.T5 | Add `tools/cleanup_state.py` script: `python -m academic_pipeline cleanup-state --before 2.5.0 --confirm`. Deletes incompatible state files. | S |
| 6.9.T6 | Add 6 tests in `tests/unit/test_persistence.py`: schema version rejection, per-agent cache isolation, dialogue cache resume, config_writer cache resume, cleanup script dry-run, cleanup script confirm. | M |

**Verification.**
```bash
uv run pytest tests/unit/test_persistence.py tests/integration/test_resume.py -x -q && \
uv run python -m academic_pipeline run "test" --thread-id _resume_smoke --output-dir ./output/_resume_smoke & \
RUN_PID=$!; sleep 60; kill -9 $RUN_PID; \
uv run python -m academic_pipeline resume _resume_smoke --output-dir ./output/_resume_smoke
```

---

### 6.10 Traceability

**Purpose.** Every numeric value, dataset description, and figure caption in the rendered paper must trace back to executed code (or be flagged as unverifiable). This is the core of Spec 1 (data-to-paper / NEJM AI port) and the structural fix for `feedback_writing_fabricates_numbers`.

**Contract.**
- *Inputs:* `ExperimentResults` with line-tagged numeric values, agent outputs containing `⟨num:label⟩` tokens, manuscript markdown.
- *Outputs:* substituted manuscript with all trace tokens resolved to numeric values; substitution audit log; code appendix (every cited line included verbatim with `\hypertarget`); notes appendix (every `[MATERIAL GAP]` and override decision); error log per token namespace (TRC).
- *Success criteria:* every trace token in manuscript resolves to a value derivable from `ExperimentResults`. Editorial gate fails on any unresolvable token. Code appendix line numbers match producer line numbers. No fabricated numbers survive the render.

**Current state (end of v2.4.0).**
- `src/academic_pipeline/traceability/` package: `copilot.py`, `dialogue.py`, `code_appendix.py`, `notes_appendix.py`, `substitution.py`, `validators.py`, `errors.py`, `context_spec.py`.
- Spec 1 Phase 1 shipped on main as merge `3912622 + 169c45b + 2400c76` (per `project_sci_traceability_progress` memory).
- 21 of 22 tasks shipped (Task 19 intentionally removed). 971 tests passing at port time, 1355 now.
- Line-level provenance shipped 2026-05-04 (merge `25076b9`): `experiment/line_tracer.py` AST tracer populates `source_code_line` via results-dict assignment analysis. Code appendix gets `\hypertarget` at producing lines.
- Documented V1 gaps:
  - `dialogue.py` helper unwired (writer↔reviewer dialogue not yet using it)
  - per-agent `ContextSpec` rollout deferred (centralized definitions not yet split per agent)
  - `producing_lines` provenance: line-level done, full producing-lines lineage TBD
- `traceability_mode: off` is the default; `partial` enables validator + notes; `full` adds dialogue + code appendix.
- Tests in `tests/unit/traceability/`.

**Target state (v2.5.0).**
- `traceability_mode: full` defaults to `true` (bundled with 6.3.T5).
- `dialogue.py` helper wired into writer↔reviewer dialogue (bundled with 6.3.T9 + 6.9.T3).
- Per-agent `ContextSpec` rolled out for the 6 highest-priority agents: `draft_writer`, `section_writer`, `editorial_synthesizer`, `peer_reviewer` (3 personas), `result_analyzer`.
- Substitution validator enforces: every numeric in the manuscript draft body has either a `⟨num:label⟩` token or a `\citetn{key}` citation pointing to a verified bibliography entry. Anything else fails editorial.
- Notes appendix auto-generated and appended to PDF.
- `errors.py` namespaces (TRC-RES, TRC-VAL, TRC-SUB, etc.) emitted to events.jsonl for postmortem grep.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.10.T1 | Wire `traceability/dialogue.py::run_writer_reviewer_dialogue` helper into writer↔reviewer dialogue (paired with 6.3.T9 + 6.9.T3). **The helper function already exists fully implemented** (verified ralph-54) — the task is just to call it from a new `SectionDialogueNode` in `writing/graph.py`. **Verified termination signal**: `DEFAULT_TERMINATION_PHRASE = "The section does not require any changes"` (exact string at `dialogue.py:25`). Loop must NOT change this string casually — any change breaks all dialogue runs. **Verified function signature**: `run_writer_reviewer_dialogue(*, writer, reviewer, prompt, deps, store: NumericalStore, max_turns=3, termination_phrase=DEFAULT_TERMINATION_PHRASE, section_name="section")`. Wires the numeric output validator (`make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)`) inside the loop. On validator failure, exception propagates — caller handles retry. Acceptance: `tests/unit/traceability/test_dialogue.py` passes with real agent message round-trip. | M |
| 6.10.T2 | Roll out per-agent `ContextSpec` for `draft_writer`. **Verified ralph-57**: `traceability/context_spec.py` (25 lines) only DEFINES the `ContextSpec` Pydantic model (2 fields: `allowed_products: list[str]`, `allowed_numerical_labels: list[str] \| Literal["all"]`). No "global per-agent definitions" exist there to move. The actual work is: define a `DRAFT_WRITER_CONTEXT_SPEC = ContextSpec(allowed_products=[...], allowed_numerical_labels=[...])` instance in `writing/agents.py` (or a new `writing/context_specs.py`), then pass it to `runtime/context.py::build_curated_context(state, spec)` when invoking the agent. The class itself stays in `traceability/context_spec.py` — only INSTANCES move into per-agent modules. The `Literal["all"]` sentinel means "full store access, no filtering" (distinct from `[]` which means "no labels allowed"). | M |
| 6.10.T3 | Repeat 6.10.T2 for `section_writer`, `editorial_synthesizer`, `peer_reviewer` (one per persona = 3 instances), `result_analyzer`. 5 more agents. **Per-agent ContextSpec instances** are added to the same module as the agent (e.g., `review/agents.py` for the 3 personas). When invoking, the call site uses `prompt = build_curated_context(state, MY_AGENT_CONTEXT_SPEC)` then `agent.run(prompt, deps=...)`. **Type check**: `build_curated_context` raises `TypeError` if `spec` is not a `ContextSpec` instance (verified `runtime/context.py:104-105`) — loop must NOT pass dict or other duck-typed object. | L |
| 6.10.T4 | Strengthen `traceability/substitution.py` to fail on unresolved tokens (currently logs a warning). Editorial gate hard-fails. | S |
| 6.10.T5 | Auto-attach `notes_appendix.py` output as a PDF appendix in `latex_compiler.py`. | S |
| 6.10.T6 | Emit per-namespace TRC error codes to `events.jsonl` (paired with 6.8.T1). | S |
| 6.10.T7 | Document the traceability flow in `docs/architecture/traceability.md`: token shape, validator gate, dialogue, appendices, error codes. ≤300 lines. | S |
| 6.10.T8 | Add 6 unit tests in `tests/unit/traceability/test_phase2.py`: dialogue helper end-to-end, ContextSpec per-agent rollout for all 6 agents, validator hard-fail on unresolved token, notes appendix in PDF. | M |

**Verification.**
```bash
uv run pytest tests/unit/traceability/ -x -q && \
test -f docs/architecture/traceability.md && \
uv run python -c "from academic_pipeline.config import PipelineConfig; c = PipelineConfig(); assert c.traceability_mode == 'full', f'mode={c.traceability_mode}'; print('OK')"
```

---

### 6.11 Quality Gate

**Purpose.** Per-node evaluator-optimizer with rubric-based scoring (max 2 iterations, default threshold 7.0/10) is the local self-correction layer. Hard vetos block known failure patterns regardless of score. Independent verifier (Opus 4.7 + `anthropic_effort: max`, 128k tokens) provides second-pass review of research claims and figures. Score trajectory tracking surfaces nodes that require evaluation but consistently pass on first try (candidates for rubric tightening).

**Contract.**
- *Inputs:* node output, rubric (per-node), threshold (default 7.0), max iterations (default 2), `anthropic_effort` for verifier (default `max`).
- *Outputs:* either accepted output, refined output (after up to 2 iterations), or `NodeQualityFailure` (if max iterations exhausted without passing). For verifier: `IndependentVerificationReport` with verdict + citations of issues. For figure verifier: `FigureVerificationReport` with VLM-based critique.
- *Success criteria:* fabricated numbers are flagged; eval panel does not score fabricated content >=7 ("hedge language exemption" closed via Spec 4/5/6 cascade in §6.4); verifier raises issues a single-pass agent missed.

**Current state (end of v2.4.0).**
- `src/academic_pipeline/runtime/evaluator.py` (~360 lines): per-node evaluator-optimizer loop. **Verified ralph-44**:
  - Verdict literal is `"PASS" | "NEEDS_IMPROVEMENT"` (not `"pass"/"fail"`).
  - **Aggregation is via MEDIAN** for ≥3 evaluators, **`min()` for exactly 2** (conservative — pick the lower score for 2-evaluator panels). Single-evaluator: trivially that score.
  - **PASS requires BOTH**: every dimension ≥ threshold AND average ≥ threshold (system prompt at `evaluator.py:38`). Not just one.
  - **Rubber-stamp warning**: any single evaluator giving ALL scores ≥ 9.5 logs `"Evaluator X gave all scores >= 9.5 (possible rubber-stamp)"` — anti-sycophancy heuristic. Loop must preserve this when extending evaluator behavior.
  - `EvaluationResult` schema: `verdict: Literal["PASS","NEEDS_IMPROVEMENT"]`, `scores: dict[dim, float]`, `feedback: str` (merged with `"[model_name] ..."` prefix per evaluator), `weakest_dimension: str | None` (set only when `NEEDS_IMPROVEMENT`), `per_model: list[EvaluatorDetail]` (un-aggregated detail for postmortem).
  - System prompt instructs evaluator to score each rubric dimension 0-10, list `weakest_dimension`, return strict PASS only on full compliance.
- `src/academic_pipeline/runtime/hard_vetos.py` (verified ralph-69, 127 lines): pattern-based blocks. **Type alias** `VetoFn = Callable[[str], str | None]` — None on pass, str (human-readable violation) on fail.
  - **Two registered vetos at HEAD**:
    1. `no_placeholder_tokens(text)` — checks 7 patterns: `(?:PROSPERO\s+)?CRD\d+[-_]?X{3,}` (PROSPERO/CRD placeholder), `NCT0?X{3,}` (NCT placeholder), `OSF[-_]?X{3,}` (OSF placeholder), `\[redacted\]` (case-insensitive), `\[INSERT[^\]]*\]` (case-insensitive), `\b(?:TODO|TBD|FIXME)\b`, `\*\*[A-Z][a-z]{0,4}\s*$` MULTILINE (dangling bold from mid-token truncation, e.g. `**Ob` at line end with no closing `**`). Hits CAPPED to first 5 in feedback for readability. Returns `"Forbidden placeholder tokens present: " + "; ".join(hits[:5])`.
    2. `no_bare_latex_commands(text)` — regex `(?<!\$)(?<!\\)\\([a-zA-Z]+)(?![^\n$]*\$)` matches `\word` not preceded by `$` or `\` and not followed by `$` on same line. Catches the common `\rho = 0.5` (no closing `$`). Cross-references against a **60-command math whitelist** (frozen): Greek lower (alpha-omega + var-variants: 26+5=31), Greek upper (Gamma/Delta/Theta/Lambda/Xi/Pi/Sigma/Upsilon/Phi/Psi/Omega = 11), math operators/symbols (infty, partial, nabla, sum, prod, int, oint = 7), decorations (sqrt, frac, hat, bar, tilde, vec, dot, ddot, boldsymbol, mathbb, mathcal, mathrm, mathit, mathbf = 14), relations (leq, geq, neq, equiv, approx, sim, simeq, propto, subset, supset, in, notin = 12), operators (pm, mp, times, div, cdot, ast, star = 7). Total ≈ 82 entries (counted by category, original "60+ symbols" undercount; whitelist may exceed if loop adds more). Text-mode commands (`\textbf`, `\textit`) and unknown commands NOT vetoed — only math whitelist triggers. Unique sorted hits, capped to first 5: `f"Bare LaTeX math commands outside $...$ mode: {', '.join(unique[:5])}. Wrap in $...$ (e.g. $\\rho$) or use Unicode (e.g. ρ)."`.
  - **`apply_hard_vetos(output_text, eval_result, vetos)` semantics**:
    - Forces `verdict = "NEEDS_IMPROVEMENT"` when ANY veto returns non-None.
    - **Preserves `scores` dict UNCHANGED** (informational only) — the LLM rubric scores stay visible for postmortem even when veto fires.
    - Overrides `feedback`: appends `" | HARD VETO: " + " | ".join(reasons)` to existing feedback, OR sets `"HARD VETO: " + reasons` when no prior feedback. Strips trailing `" |"`.
    - Sets `weakest_dimension = "hard_veto"` (special sentinel — dashboard/audit consumers must treat this as "structural failure" not a real rubric dimension).
    - Returns NEW frozen `EvaluationResult` (Pydantic `model_config = ConfigDict(frozen=True)` — old result not mutated).
  - **`[PENDING: ...]` SANCTIONED EXCEPTION** (verified line 24-25 docstring): the `[INSERT...]` pattern intentionally does NOT match `[PENDING: ...]` because `[PENDING: ...]` is the SANCTIONED form for explicit deferrals per `writing/specs/section_writer.yaml line 67-75`. Loop adding new placeholder vetos MUST preserve this carve-out — agents emit `[PENDING: details to be added in next pass]` deliberately and breaking this would block legitimate progress markers. Conversely, agents writing finalized content MUST use `[PENDING: ...]` for known gaps, never `[INSERT ...]`/TODO/TBD/FIXME.
- `src/academic_pipeline/runtime/score_trajectory.py` (verified ralph-70, 145 lines): pure utility functions for tracking review-score deltas across revision rounds. **NO state, NO I/O, NO class** — stateless module-level functions only. Persistence is TARGET STATE in §6.11.T1, not yet implemented.
  - **`DIMENSIONS` frozen list (8)**: `argument_strength`, `evidence_quality`, `methodological_rigor`, `writing_clarity`, `citation_accuracy`, `structural_coherence`, `originality`, `overall`. Loop ADDING dimensions must update both `DIMENSIONS` AND `_LABEL_TO_SNAKE` mapping AND every YAML reviewer rubric in lockstep.
  - **CRITICAL: Score scale is 0-100, NOT 0-10** (verified line 142 `if 0 <= score <= 100`). The pipeline has TWO incompatible scoring scales: `runtime/evaluator.py` uses 0-10 floats per rubric dimension; `runtime/score_trajectory.py` parses 0-100 ints from peer-review text. **Loop must NOT mix these** — converting between scales requires explicit `score * 10` / `score / 10` and rounding semantics. AP62 codifies.
  - **`compute_deltas(current, previous)`**: returns `dict[dim, int]` of `current - previous` for each dimension that appears in both inputs AND in `DIMENSIONS`. Missing dimensions are silently skipped (NOT errored — this is intentional for partial reviews).
  - **`detect_regression(deltas, threshold=-3)`**: returns `list[str]` of dimension names where `delta < threshold`. Default `-3` means "drop of 4+ points" triggers a flag. Loop must NOT change default without updating tests AND the §6.11 contract.
  - **`check_early_stop(deltas, threshold=3, *, has_p0=False)`**: returns `True` ONLY when ALL of (a) `has_p0 is False`, (b) `deltas` is non-empty, (c) every `delta < threshold`. Empty deltas → False (cold start, no convergence claim possible). Any P0 → False (critical issues must be resolved). Loop must keep `has_p0` keyword-only — positional usage breaks call sites.
  - **`parse_scores_from_review(review_text)` heuristics** (TWO regex patterns):
    - Table row: `\|\s*(?P<dim>[A-Za-z][A-Za-z_ ]+?)\s*\|\s*(?P<score>\d{1,3})(?:\s*/\s*100)?\s*\|`
    - Key-value: `(?P<dim>[A-Za-z][A-Za-z_ ]+?)\s*:\s*(?P<score>\d{1,3})(?:\s*/\s*100)?(?:\s|$)`
    - **First-write-wins** within a single parse (`if dim not in scores`) — multiple scores for same dimension keep the FIRST seen. Loop must preserve this so reviewer "summary table at top" wins over "deep-dive table later".
    - Score validation: `0 <= score <= 100` (sanity bound — anything outside dropped silently).
    - `_normalize_dimension(raw)`: tries `_LABEL_TO_SNAKE` lookup on `raw.strip().lower().replace("_", " ")` first, then direct snake match. Returns None if neither works (silently dropped — no warning logged).
  - **Loop modifying parse heuristics MUST add a corresponding test** in `test_score_trajectory.py` — the regex is brittle and reviewer agent prompts can drift the format easily.
- `independent_verifier` agent at `research/specs/independent_verifier.yaml` — Opus 4.7, `anthropic_effort: max`, `max_tokens: 128000`.
- `figure_verifier` agent at `writing/specs/figure_verifier.yaml` — same settings, VLM-capable.
- All 7 reviewer/verifier agents promoted to `anthropic_effort: max` in v2.4.0.
- GPT-5.2 dependency removed in v2.4.0; FallbackModel wrapper deleted; both verifier legs were Opus, made the wrapper pointless.
- Tests: `tests/unit/runtime/test_evaluator.py`, `test_hard_vetos.py`, `test_score_trajectory.py`.
- Memory note: `feedback_eval_panel_blind_spot` — 3-model panel scored fabricated Results 9/10 fooled by hedge language. Closed structurally by Specs 4 + 5 + 6 in §6.4, not by retuning the per-node panel.

**Target state (v2.5.0).**
- Score trajectory persists per-thread (currently in-memory). Reports surface in the dashboard (paired with §6.8).
- Hard vetos extended with: hedge-language detection in Results sections (`"interim"`, `"subject to revision"`, `"awaits full search"`), missing trace token in numeric claims, missing thesis-advancing role.
- `evaluator.py` integrates with `traceability/validators.py` so a node's evaluator considers trace-token coverage in its rubric.
- Per-node rubric thresholds individually tunable in `configs/default.yaml` under `node_quality_thresholds: {synthesis: 7.5, draft_writer: 7.0, ...}`.
- `independent_verifier` consumes `Thesis` and `CascadeResult` to produce a "thesis-grounded verification" rather than only claim-level.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.11.T1 | Persist `score_trajectory.py` per-thread to `.pipeline_runs/<thread-id>_scores.json`. Surface in dashboard panel (paired with 6.8.T2). | S |
| 6.11.T2 | Extend `runtime/hard_vetos.py` with hedge-language patterns and missing-trace-token detection. **Two categories — keep separate** per Spec 1 design doc: (a) **Hedge phrases (5)** trigger retry via PydanticAI `ModelRetry` (TRC001 NumericValidatorRetry) — verified ralph-56 verbatim from `validators.py:37-39`: `"approximately"`, `"around"`, `"roughly"`, `"circa"`, `"~"` — only flagged when within `HEDGE_PROXIMITY_TOKENS` (default 5, configurable) **tokens BEFORE** a `⟨num:label⟩` token (direction matters); (b) **Aborting phrases (9, NOT 4 as earlier PRD said)** trigger fail-loud (raises `UnexpectedModelBehavior`, no retry — note: NOT `NumericValidatorAbort/TRC002` despite `errors.py` defining that class; loop should reconcile). Verified ralph-56 verbatim from `validators.py:42-45`: `"[insert"`, `"[unknown"`, `"[to be determined"`, `"[to be"` (broader catch-all for `[to be ...]` placeholders), `"subject to revision"`, `"pending full search"`, `"<insert"`, `"<unknown"`, `"<missing"` (3 angle-bracket variants for HTML-style placeholders). **Case-insensitive** matching via `phrase.lower() in text.lower()`. Flagged anywhere in section body. Pattern lists in `traceability/validators.py` (PRD said `_patterns.py` — actually `validators.py:37-45`; `_patterns.py` has only the regex `NUM_TOKEN_PATTERN`). | M |
| 6.11.T3 | Wire `traceability/validators.py` into `evaluator.py`: a node's evaluator includes a "trace-token coverage" dimension in its rubric. | M |
| 6.11.T4 | Add per-node threshold map in `config.py`: `node_quality_thresholds: dict[str, float]`. Loaded from `configs/default.yaml`. Backward compat: missing entry falls back to `node_quality_threshold` global default. | S |
| 6.11.T5 | Modify `independent_verifier.yaml` to consume `Thesis` and `CascadeResult`. Update prompt: "verify that the manuscript advances the thesis; verify that the cascade verdict is consistent with the manuscript content." | S |
| 6.11.T6 | Add 5 unit tests in `tests/unit/runtime/test_evaluator_phase2.py`: hedge-language veto fires, missing-trace-token veto fires, per-node threshold map honored, trace-token coverage dimension in rubric, independent_verifier sees thesis + cascade. | M |

**Verification.**
```bash
uv run pytest tests/unit/runtime/ -x -q -k 'evaluator or hard_vetos or score_trajectory or verifier'
```

---

### 6.12 Config + SDK Surface

**Purpose.** Single, type-safe configuration object. Public Python API for embedding the pipeline in other tools. Examples that double as smoke tests. `py.typed` marker so downstream consumers get type information.

**Contract.**
- *Inputs:* env vars, `.env`, `configs/default.yaml`, `configs/dev.yaml`, init kwargs to `PipelineConfig`.
- *Outputs:* validated `PipelineConfig` instance; public `Pipeline`, `PipelineResult`, `DEFAULT_CONFIG` from `academic_pipeline` package; runnable scripts in `examples/`.
- *Success criteria:* every config field documented; precedence order (init > env > .env > dev.yaml > default.yaml > defaults) honored; `examples/` scripts run end-to-end and pass `make check`.

**Current state (end of v2.4.0).**
- `src/academic_pipeline/config.py` (~410 lines): `PipelineConfig(BaseSettings)` with full Pydantic validation. `settings_customise_sources` enforces precedence.
- `configs/default.yaml`, `configs/dev.yaml`.
- `src/academic_pipeline/__init__.py` exports `Pipeline`, `PipelineConfig`, `PipelineResult`, `DEFAULT_CONFIG` with explicit `__all__`.
- `src/academic_pipeline/sdk/pipeline.py`, `sdk/result.py`, `sdk/events.py`. **`Pipeline` constructor signature** (verified ralph-45): `Pipeline(topic: str, *, thread_id: str | None = None, interactive: bool = True, revision_instructions: str = "", persistence_dir: Path | None = None, use_dbos: bool = False, paper_config: PaperConfig | None = None)` — 7 params total, 1 positional + 6 keyword-only. Auto-generated `thread_id` format: `f"run-{datetime.now().strftime('%m%d-%H%M')}_{uuid.uuid4().hex[:4]}"` → `run-MMDD-HHMM_xxxx` (4-char hex suffix). Loop generating thread_ids elsewhere must follow this format. **Persistence backend is SQLite** (`SqliteStatePersistence` at `.pipeline_runs/pipeline.sqlite`), NOT file-based — earlier PRD said `FileStatePersistence` but no such class exists (verified `persistence.py:62`). State serialized via `pydantic.TypeAdapter(PipelineState)`. **DBOS opt-in via `use_dbos=True`** (default `False`, matches §26 D29). **`Pipeline.observe(callback)` does NOT exist at HEAD** — confirmed as net-new work in §6.12.T2.
- `src/academic_pipeline/py.typed` marker present.
- `examples/` directory with 4 runnable scripts (current set: enumerate during T3 before adding more).
- `skills/` directory loaded by `config.py::SKILLS_DIRS = [str(PROJECT_ROOT / "skills")]` via `pydantic-ai-skills>=0.7.0`. Two skill packs: `skills/autogluon/SKILL.md` (7.2KB, consumed by experiment ml_engineer / config_writer agents), `skills/exa-research/SKILL.md` (1.5KB, consumed by bibliography + experiment_designer agents).
- Tests: `tests/unit/test_config.py`, `tests/unit/sdk/`.
- 8 SCI Phase-1 flags currently default `false`. Various other flags (`force_experiment`, `experiment_use_docker`, `enable_node_evaluation`, etc.) honor sensible defaults.
- **Version drift:** `VERSION=2.3.0`, `pyproject.toml=0.2.0`, `CHANGELOG.md` shows `[2.4.0] — 2026-05-02` shipped + `[Unreleased]`, `README.md` badges show `v2.3.0`. Three sources of truth disagree.
- **Declared-but-unused dependencies:** `pydantic-ai[mcp,dbos]` (DBOS disabled per `project_dbos_compat`; MCP not used per CLAUDE.md "Exa direct tools, no MCP"), `fastapi>=0.115.0`, `uvicorn[standard]>=0.32.0` (no in-source imports).

**Target state (v2.5.0).**
- All 8 Phase 2 SCI flags flipped to `true` in `configs/default.yaml` (paired with each component's deltas).
- `legacy_*` escape hatches added for each flipped flag. Defaults `false`. Documented in CHANGELOG.
- Per-node quality threshold map in config (paired with 6.11.T4).
- New `examples/`:
  - `examples/run_with_acl_template.py`
  - `examples/run_with_breadth_mode.py`
  - `examples/inspect_cascade_verdict.py`
  - `examples/replay_from_events_jsonl.py`
- SDK adds `Pipeline.observe(callback)` to subscribe to events programmatically (cleaner than tailing `events.jsonl` from Python).
- `docs/architecture/sdk.md` documents the public surface, with one snippet per `__all__` symbol.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.12.T1 | Bundle SCI flag flips: `chain_of_ideas_enabled`, `novelty_gate_enabled`, `pointwise_novelty_enabled`, `persona_reviewers_enabled`, `cascaded_review_enabled`, `exploration_breadth_enabled`, `traceability_mode: full`, plus default-on for checklist ethics. Add `legacy_*` escape hatches per flag. (Paired with each subsystem's `T1`/`T5`.) | S |
| 6.12.T2 | Add `Pipeline.observe(callback: Callable[[Event], None]) -> Cancellable` to `sdk/pipeline.py`. Calls callback on every event emission. Tests in `tests/unit/sdk/test_observe.py`. | M |
| 6.12.T3 | Add 4 example scripts in `examples/` and verify each runs end-to-end with TestModel agents. | M |
| 6.12.T4 | Write `docs/architecture/sdk.md` with one snippet per public `__all__` symbol. ≤200 lines. | S |
| 6.12.T5 | Add `node_quality_thresholds: dict[str, float] = Field(default_factory=dict)` to `PipelineConfig` (bundled with 6.11.T4). | XS |
| 6.12.T6 | **Version unification.** Bump `VERSION` → `2.5.0`, `pyproject.toml::version` → `2.5.0`, README badges → `v2.5.0`. Add a `tools/check_version_consistency.py` script invoked by `make check` that fails CI if the three sources disagree. | S |
| 6.12.T7 | **Declared-but-unused dependency decision.** Remove `pydantic-ai[dbos]` extra (DBOS confirmed disabled). Remove `pydantic-ai[mcp]` extra unless §6.13 traces it as actually-loaded by a transitive (verify with `uv tree`). For `fastapi` + `uvicorn`: either remove (preferred) or document the consumer (e.g., dashboard v2 §6.8.T5 if it ships an HTTP endpoint). **ALSO investigate `defusedxml>=0.7.1`** — declared as production dep at `pyproject.toml:34` but `grep -r defusedxml src/` returns ZERO matches at HEAD. Either (a) transitive consumer exists (verify with `uv tree`) and dep stays as explicit pin, or (b) it's stale and should be removed. Update CHANGELOG. | S |
| 6.12.T8 | **Skill packs documented.** Add `docs/architecture/skills.md` describing `SKILLS_DIRS` loading, the contract for a skill pack (SKILL.md frontmatter, files), and the two existing packs. Add 2 unit tests in `tests/unit/test_config.py` asserting `SKILLS_DIRS` resolves and both packs load cleanly. | S |
| 6.12.T9 | **Documentation index.** Refresh `docs/README.md` (currently 788B placeholder) into a TOC for the v2.5.0 doc set: PRD (this file), architecture/ (recovery, rendering, traceability, sdk, skills), superpowers/ (specs + plans), user/ (existing). Doc builds remain ad-hoc (mkdocs not in scope for v2.5.0). | XS |

**Verification.**
```bash
uv run pytest tests/unit/test_config.py tests/unit/sdk/ -x -q && \
uv run python -c "from academic_pipeline import Pipeline, PipelineConfig, PipelineResult, DEFAULT_CONFIG; print('imports OK')" && \
for ex in examples/*.py; do uv run python "$ex" --dry-run || exit 1; done && \
test -f docs/architecture/sdk.md && test -f docs/architecture/skills.md && \
uv run python tools/check_version_consistency.py
```

---

### 6.13 Observability

**Purpose.** Trace every agent call, tool use, and HTTP request to Pydantic Logfire so failures past the events.jsonl record are debuggable. Degrade gracefully when Logfire is unreachable. Provide structured Python logging with rotating file handler as the durable local fallback.

**Contract.**
- *Inputs:* `LOGFIRE_TOKEN` (env), `log_dir` config, `log_max_bytes`, `log_backup_count`.
- *Outputs:* spans in Logfire project `research-demo` for every PydanticAI agent call (via `instrument_pydantic_ai`), every httpx request (via `instrument_httpx(capture_all=True)`); rotating logfile at `logs/academic_pipeline.log` (10 MB × 5 backups by default).
- *Success criteria:* Logfire spans appear within 5 s of agent call completion when token is present; pipeline continues unaffected when token absent (`send_to_logfire="if-token-present"`); local logfile rotation does not lose events under burst.

**Current state (end of v2.4.0).**
- `src/academic_pipeline/observability.py` (verified ralph-71, **174 lines**, NOT 150 as PRD prose said) bundles SIX responsibilities — loop must understand the bundling before refactoring:
  1. **`configure_ssl()`** — `truststore.inject_into_ssl()` for OS-cert-store SSL (Zscaler proxy support). Graceful `ImportError` fallback to default certifi (no error raised).
  2. **`configure_observability()`** — Logfire `service_name="academic-pipeline"`, `send_to_logfire="if-token-present"`, `instrument_pydantic_ai()`, `instrument_httpx(capture_all=True)`, then chains `install_keepalive_provider_patch()`. ALL Exception caught + logged at debug (silent skip when Logfire unreachable).
  3. **`install_keepalive_provider_patch()`** — monkey-patches BOTH `anthropic.AsyncAnthropic.__init__` AND `openai.AsyncOpenAI.__init__` (verified line 79-100; OpenAI patched even though GPT-5.2 dependency was removed in v2.4.0 — defensive for any future OpenAI usage). Re-entrancy guard via `__keepalive_patched__` sentinel attribute (loop monkey-patching MUST follow this pattern). Patched `__init__` does `kwargs.setdefault("http_client", _get_shared_keepalive_client())` — explicit `http_client=` arg in caller wins, fallback to shared.
  4. **`_SHARED_KEEPALIVE_CLIENT` module-level singleton** (verified line 14) — one connection pool / one set of keepalive sockets shared across **all 38+ Agent.from_file() constructions**. Lazy init via `_get_shared_keepalive_client()` first call. Loop must NOT create per-agent clients or this collapses to 38 separate pools.
  5. **`shutdown_observability()`** — `logfire.shutdown()` to flush span exporters before process exit. ALL Exception silently caught (so shutdown never blocks process exit).
  6. **`init_dbos()` + `launch_dbos()` two-step lifecycle** (verified line 139-173). DBOS init MUST happen BEFORE any DBOSAgent registered; launch MUST happen AFTER. **`_cancel_stale_workflows(db_path)` runs BEFORE init** — issues `UPDATE workflow_status SET status='CANCELLED' WHERE status='PENDING'` against `.pipeline_runs/dbos.sqlite`. Without this, `DBOS.launch()` blocks FOREVER trying to recover crashed-PENDING workflows from a previous run. **DBOS db_path is hard-coded at `.pipeline_runs/dbos.sqlite`** — loop must NOT change without updating cleanup logic + adding migration. Both functions return bool/None and silently skip on ImportError (DBOS optional).
- `src/academic_pipeline/logging_config.py` configures rotating Python `logging` with `RotatingFileHandler`. Wired into `cli.py::supervised_run` and `cli.py::watchdog` (commit `6bc3cf5`).
- Tests: `tests/unit/test_observability.py` (~30 lines).
- Logfire span schema is whatever PydanticAI emits by default — no custom enrichment.
- Recovery layer events (§6.6) are not yet enriched into spans (only events.jsonl).
- **`runtime/parsing.py` dialogue-health checks** (verified ralph-71, 64 lines — NOT documented in PRD before this iter): `check_dialogue_health(messages, window=5)` scans last `window` ASSISTANT messages for two patterns:
  1. **Persistent Agreement**: 7 markers (`i agree`, `you're right`, `good point`, `no issues`, `that's correct`, `fair point`, `well said`) — case-insensitive substring match. **3+ CONSECUTIVE messages** containing any marker triggers warning. Counter RESETS to 0 on first non-agreement message (NOT cumulative). Loop must keep "consecutive" semantics — converting to "any 3 in window" would over-warn legitimate review consensus.
  2. **Conflict Avoidance**: 3 regex patterns (`no critical issues`, `no major issues`, `no minor issues`) — ALL THREE must match in same message to trigger (strict AND, not OR). Breaks after first match (only one warning per call). Loop converting to OR semantics would falsely flag every "no critical issues" finding.
- Module name `parsing.py` is misleading — only function exposed is `check_dialogue_health`; this is dialogue health, NOT structured-output parsing. Loop must not add structured-output parsers here without renaming module.
- **`runtime/context.py` shared context builder** (verified ralph-72, 146 lines — also undocumented in PRD before this iter despite being the most-called runtime utility, used by `research/graph.py` 11× + `pipeline/nodes.py` + writing/review subgraphs). FOUR exposed functions:
  1. **`extract_field_text(state, field_name)`** — dispatch tower for state-field rendering. Order matters: falsy → `""`, `pydantic.BaseModel` → `model_dump_json(indent=2)`, `dict` → `dict.get("raw")` first (returns `str(raw)` if present, else `json.dumps(value, indent=2, ensure_ascii=False, default=str)`), `list` → `"\n".join(str(item) for item in value)`, fallback → `str(value)`. The `dict["raw"]` short-circuit is load-bearing — many state dicts wrap raw LLM text under `"raw"` key for round-tripping; loop changing this order would re-stringify wrapped objects and bloat prompts. **`ensure_ascii=False`** preserves Unicode (Greek, math) in JSON.
  2. **`build_context(state, keys, node_name=None)`** — concatenates `f"{key}:\n{text}"` blocks separated by `"\n\n"` for each key whose `extract_field_text` is non-empty. **CRITICAL SIDE EFFECT** when `node_name` is supplied AND `state.revision_context.target_node == node_name`: appends a REVISION INSTRUCTIONS block AND **clears `state.revision_context = None`** (single point of responsibility — verified line 77). Loop MUST NOT add another consumer of `revision_context` or duplicate revision instructions on second call. **Verified revision block format** (line 64-72):
     ```
     REVISION INSTRUCTIONS:
     Round: {round}
     Source: {source}
     Weakest dimension: {weakest_dimension}
     Feedback: {feedback_summary}
     Issues to address:
     {issues_text}
     
     Your previous output:
     {previous_output}
     
     Revise your output to address these issues. Do not regenerate from scratch — improve what you wrote.
     ```
     Issue line: `f"- [{issue.severity}] {issue.dimension}: {issue.description}. Recommendation: {issue.recommendation}"`. Empty issues list → `"- No specific issues listed."` (placeholder).
  3. **`build_curated_context(state, spec)`** — ContextSpec-aware variant. Iterates `spec.allowed_products` (NOT all state fields). Adds numerical-store table when both: store is a `NumericalStore` instance AND `store.products` non-empty AND `spec.allowed_numerical_labels` resolves to ≥1 label in `store.products`. **`spec.allowed_numerical_labels == "all"` is a SENTINEL STRING** (verified line 116) — NOT a list — passes through all keys. Otherwise list/iterable filtered by `lbl in store.products`. Table format: header line `"Available numerical values (cite using ⟨num:label⟩):"` then `f"- {label} = {p.value}{unit_str} — {p.context}"` per row (unit omitted entirely when empty, NO trailing space). **Strict `isinstance(spec, ContextSpec)`** — raises `TypeError(f"build_curated_context requires ContextSpec, got {type(spec)}")` (line 104-105) — no duck typing, no dict shortcut.
  4. **`format_health_prefix(messages)`** — wraps `check_dialogue_health(messages)` output. Format: `f"[DIALOGUE HEALTH WARNING: {'; '.join(warnings)}. Consider whether genuine consensus has been reached or if challenges are being suppressed.]\n\n"`. Returns `""` when no warnings (NOT `None` — callers can unconditionally `prompt = format_health_prefix(...) + base_prompt` without guard).
- **TraceLogger durable disk fallback (verified ralph-68 from `runtime/trace_logger.py`).** Independent of Logfire — every `traced_agent_run` writes a per-call markdown + raw-JSON pair to disk so traces are debuggable even when Logfire is unreachable. Layout:
  - `output/<run_id>/<phase>/traces/{NN}_{name}.md` — human-readable markdown rendering, sequence number per phase (`{NN}` = `01`, `02`, …; counter at `_sequence: dict[str, int]` is per-`TraceLogger`-instance).
  - `output/<run_id>/<phase>/traces/raw/{NN}_{name}.json` — full unmodified `all_messages_json()` decode + usage block + optional `evaluation` block (verdict, scores, feedback, weakest_dimension, per_model).
  - **Truncation rules** that PRD consumers (dashboard, audits) MUST mirror:
    - `_MAX_TOOL_RESULT_CHARS = 3000` (markdown only) — tool returns longer than 3 KB get `... [truncated]` suffix in the .md but raw JSON always has full content.
    - Thinking parts truncated to 2000 chars in markdown; raw JSON preserves full thinking.
  - **3-fallback message serialization** that NEVER raises — `result.all_messages_json().decode()` → `[m.model_dump() for m in result.all_messages()]` → placeholder `[{"parts": [{"part_kind": "system-prompt", "content": "[messages unavailable: …]"}]}]`. Trace files are always written; the loop must not assume traces can fail.
  - **Eight `part_kind` types rendered**: `system-prompt`, `user-prompt`, `retry-prompt`, `thinking`, `text`, `tool-call`, `tool-return`, plus implicit `request_num` counter for multi-turn renders. Loop adding new part_kinds (e.g. for new PydanticAI versions) MUST extend `_format_readable` AND keep raw JSON path verbatim.
  - **Auto-prettify of structured outputs** (verified line 211-225): when a `text` part starts with ```` ```json ```` fence OR is valid JSON, it's re-rendered via `_render_json_as_markdown` → `_json_to_md` (recursive: keys → `**Title Case:**`, lists numbered, nested dicts indented 4 spaces). Loop MUST NOT bypass this in dashboards — markdown traces are the operator-friendly artifact.
  - **`_AGENT_RUN_TIMEOUT_S = 480.0` rationale block** (`trace_logger.py:21-27`): "8-minute wall-clock cap per agent.run. Must be LESS than recovery/watchdog.py max_idle_s (600s) so wedged proxy-SSE calls raise AgentTimeoutError → the snapshot is recorded as 'error' → auto-resume picks up cleanly. With the old 900s cap, the watchdog killed the process group at 600s instead, wasting 5 extra minutes per cycle and corrupting in-flight snapshots. Lowered after run-0504-1802_ec44 post-mortem (5 wedge-resume cycles observed)." This is the canonical reference point for §3.2 ordering invariant; loop MUST treat the comment as load-bearing documentation, not folklore.

**Target state (v2.5.0).**
- Span enrichment for the new event types added in §6.8.T1 (`recovery_event`, `doi_gate_failure`, `cascade_verdict`, `novelty_gate_verdict`, `ethics_checklist_result`). Each gets its own Logfire span name and structured attributes.
- One-line "tracing health" line emitted at pipeline start: token present/absent, project name, expected dashboard URL.
- Documented degradation path in `docs/architecture/observability.md` for: Logfire down, token revoked, network partition.
- Per-agent span tagging (agent name as span attribute) so Logfire queries can filter by agent.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.13.T1 | Add span enrichment for the 5 new event types (paired with §6.8.T1). Each emits a Logfire span via `logfire.span(...)` alongside the events.jsonl write. | M |
| 6.13.T2 | Emit "tracing health" line at startup (`observability.py::configure`): log Logfire status (`enabled`/`token-absent`), project name, dashboard URL hint. | XS |
| 6.13.T3 | Add per-agent tag to spans via PydanticAI `Agent` name attribute. Verify visible in Logfire queries. | S |
| 6.13.T4 | Write `docs/architecture/observability.md`: span schema, degradation modes, how to debug a missing trace, how to swap Logfire project. ≤200 lines. | S |
| 6.13.T5 | Add 4 unit tests in `tests/unit/test_observability.py`: degradation when no token (no exception), span enrichment for cascade verdict, per-agent tag present, logfile rotation under simulated burst. | M |

**Verification.**
```bash
uv run pytest tests/unit/test_observability.py -x -q && \
test -f docs/architecture/observability.md && \
LOGFIRE_TOKEN= uv run python -m academic_pipeline run "test" --thread-id _obs_smoke --output-dir ./output/_obs_smoke 2>&1 | grep -q "Logfire" && \
echo "OK"
```

---

### 6.14 CI / Release Pipeline

**Purpose.** Every PR runs lint + typecheck + small tests; main branch additionally runs medium tests (Docker integration); tag pushes trigger publish workflow. Self-hosted runner secret injection is documented and stable. Version bump is a single command.

**Contract.**
- *Inputs:* git push (PR or main), git tag `vX.Y.Z`.
- *Outputs:* `ci.yml` job results (lint, typecheck, test matrix); `publish.yml` artifacts on tag (PyPI? GitHub release? — must be specified, see §6.14.T2); CHANGELOG entry rendered into the GitHub Release body.
- *Success criteria:* main branch is always green for `make check`; tagged releases produce reproducible artifacts; rollback (delete tag, retag) does not corrupt artifact registry.

**Current state (end of v2.4.0).**
- `.github/workflows/ci.yml` (2.3KB): jobs `lint`, `typecheck`, `test` (matrix: Python 3.12 + 3.13). Self-hosted runners. `concurrency` cancels in-progress runs on the same branch.
- `.github/workflows/publish.yml` (332B): exists but contents not surfaced in PRD (small file — likely tag-trigger PyPI publish or GitHub Release). **Audit required.**
- `Makefile` targets cover `check` (lint + typecheck + test), `test-integration` (medium), `test-e2e` (large), `test-traceability`, `test-traceability-medium`, `test-traceability-regressions`.
- `pre-commit-config.yaml` (472B) — likely ruff hook.
- No automated medium-test job in CI today (Docker required, must run on a runner with Docker available).
- No automated version-consistency check (§6.12.T6 adds the script; CI must run it).

**Target state (v2.5.0).**
- CI matrix unchanged (3.12 + 3.13).
- New job `test-medium`: runs `make test-integration` on a runner with Docker installed. Required for merge to main; not gated on PRs from forks.
- New job `version-consistency`: runs `tools/check_version_consistency.py` (added in §6.12.T6). Required for all PRs.
- New job `pre-commit`: runs `pre-commit run --all-files`. Required.
- `publish.yml` documented and verified: source-of-truth for what `git tag v2.5.0 && git push --tags` actually does (PyPI? GitHub Release? Both?). README references the workflow.
- Self-hosted runner secret-injection model documented: which secrets, how rotated, who owns.
- Tag protection rule on `vX.Y.Z` enforced via GitHub branch/tag protection.

**Delta.**

| ID | Task | Estimate |
|---|---|---|
| 6.14.T1 | Add `test-medium` job to `ci.yml` running `make test-integration`. Gate on `lint` + `typecheck` passing. Skip on fork PRs (needs Docker). | M |
| 6.14.T2 | **Audit `publish.yml` and document.** Read what it does today; confirm trigger (`on.push.tags: 'v*'`?), target registry (PyPI? GitHub Release?), and required secrets. Write findings into `docs/architecture/release.md`. If broken or vestigial, replace with a tag-triggered GitHub Release that uploads `dist/*` (built via `uv build`) and renders the CHANGELOG entry as the release body. | M |
| 6.14.T3 | Add `version-consistency` job invoking `tools/check_version_consistency.py` (paired with §6.12.T6). | XS |
| 6.14.T4 | Add `pre-commit` job running `pre-commit run --all-files --show-diff-on-failure`. | XS |
| 6.14.T5 | Document self-hosted runner secret model in `docs/architecture/release.md`: which secrets (`ANTHROPIC_API_KEY`, `EXA_API_KEY`, `LOGFIRE_TOKEN`, `S2_API_KEY`, `PYPI_TOKEN`?), how injected, rotation schedule. | S |
| 6.14.T6 | Configure GitHub tag protection rule on `vX.Y.Z` pattern (cannot be force-deleted; only repo admins can push). Manual GitHub UI step; document in `docs/architecture/release.md`. | XS |
| 6.14.T7 | **Resolve pyright/basedpyright inconsistency.** `Makefile:98` invokes `npx basedpyright`; `pyproject.toml::dev` pins `pyright>=1.1`; `.github/workflows/ci.yml` runs `uv run pyright`. Three sources, two tools. Pick one (recommended: basedpyright per Makefile direction) and update the other two. Add to §28 anti-pattern catalog if it's a recurring drift class. | XS |
| 6.14.T8 | **Add security scanners to CI.** `pyproject.toml::dev` declares `pip-audit>=2.7` and `bandit>=1.7` but neither runs in `.github/workflows/ci.yml`. Add both as required jobs (per-PR) — pip-audit catches CVEs in deps, bandit catches AST-level Python security smells. | S |
| 6.14.T9 | **mkdocs decision.** `pyproject.toml::dev` declares `mkdocs-material>=9.5`, `mkdocstrings[python]>=0.27`, `mkdocs-gen-files>=0.5` but no `mkdocs.yml` exists at repo root. PRD §6.12.T9 says "mkdocs not in scope for v2.5.0". Either (a) keep deps for v2.6.0+ and document in `docs/README.md` why they're declared but not yet wired, or (b) remove deps. Recommendation: keep + document. | XS |

**Verification.**
```bash
uv run python tools/check_version_consistency.py && \
test -f docs/architecture/release.md && \
yq '.jobs | keys' .github/workflows/ci.yml | grep -qE '(test-medium|version-consistency|pre-commit)' && \
gh workflow view publish.yml --ref main 2>/dev/null | head -20
```

---

### 6.15 Output Verification + LLM-as-Judge Evaluators

**Purpose.** "Tests pass + flags flipped" does not prove the pipeline produces SCI-clearable papers. This component closes the gap with three layers stacked in order: (a) **error analysis** on historical traces using the open-coding → axial-coding → structured-labeling methodology to ground the failure-mode taxonomy in actual production behavior; (b) **golden reference fixtures** with code-based structural assertions on every output; (c) **per-failure-mode LLM-as-Judge evaluators** with calibrated TPR/TNR + Rogan-Gladen bias-corrected success-rate estimation + bootstrap CIs, validated by a held-out test split that never appears in any judge prompt. v2.5.0 release gates on the regression suite passing all 5 fixture topics AND Jackson's spot-review approval on 3 sample papers (§3.3 gates 9–12).

**Contract.**
- *Inputs:*
  - 100–200 historical traces from `output/` archive, labeled by Jackson per failure mode using the chapter 3 methodology (open coding → axial coding → structured labels);
  - 5 canonical fixture topics under `tests/fixtures/golden/` with `topic.txt`, `expected.yaml`, `reference_paper.bib`, `metrics.yaml`;
  - raw production traces (latest N runs from `output/`).
- *Outputs:*
  - (a) `make test-regression` exit code + per-fixture report;
  - (b) per-failure-mode true-pass-rate point estimate + 95% bootstrap CI;
  - (c) `docs/v2.5.0-spot-review.md` with 3 checked-and-signed paper review boxes (one of which compares v2.4.0 ↔ v2.5.0 on the same topic by eyeball).
- *Success criteria:* per §3.3 gates 9–12 — every fixture passes structural assertions; every judge has TPR ≥ 0.85 AND TNR ≥ 0.85 on its test split; bias-corrected pass rate per failure mode has CI lower bound ≥ 0.70 over 50 production runs; Jackson signs off on 3 papers (one of which is a v2.4.0/v2.5.0 side-by-side).

**Current state (end of v2.4.0).**
- `tests/fixtures/golden/` does NOT exist.
- `tests/fixtures/labeled_traces/` does NOT exist.
- No structural assertion library (`tools/output_assertions.py` absent).
- No LLM-as-Judge framework — `src/academic_pipeline/evaluation/` package does not exist.
- The eval panel (§6.11) computes scores but is **not validated against human labels**. Memory entry `feedback_eval_panel_blind_spot` documents a case of fabricated content scored 9/10 by the panel (fooled by hedge language) — that's the failure mode this component exists to catch.
- No bias-corrected success-rate machinery. No bootstrap CI. No `judgy`-equivalent.
- No documented failure-mode taxonomy. No standard list of named failure modes — observations live scattered across feedback memories (`feedback_writing_fabricates_numbers`, `feedback_eval_panel_blind_spot`, `feedback_knowledge_graph_weakness`, `feedback_ethics_node_shallow`, `feedback_depth_gaps`).
- ~50 historical pipeline runs sit unlabeled in `output/`.

**Target state (v2.5.0).**
- A documented failure-mode taxonomy at `docs/evaluation/failure-modes.md`, derived from open-coding 100+ historical traces, refined via axial coding into 6 named modes: `hedge_language_in_results`, `thesis_incoherence`, `persona_tone_mismatch`, `citation_orphan`, `fabricated_numeric`, `imrad_incompleteness`. Each mode has a one-sentence definition, 3+ representative trace excerpts, and a Pass/Fail rubric.
- 5 canonical fixture topics with full golden artifacts, generated via the dimension-tuple-query method (not generic LLM "make me 5 topics") — dimensions: domain (medical / NLP / CV / time-series / ML-theory), novelty (saturated / underexplored), experiment-requirement (none / tabular / timeseries / multimodal). Tuples chosen to force coverage across all three dimensions.
- `tools/output_assertions.py` with 12–16 atomic, binary, code-based assertions. Reference-free where possible (page count, regex for IMRaD section headings, AST-style scan for trace-token presence in numeric claims) per chapter 5's reference-free metric guidance.
- `src/academic_pipeline/evaluation/` package:
  - `judges/` — 6 judge YAML specs + Python wrappers, one per failure mode. Binary Pass/Fail output. Few-shot examples drawn ONLY from the train split. Prompt structure follows chapter 5: clear task, precise Pass/Fail definitions, few-shot examples, JSON `{reasoning, answer}` output.
  - `splits.py` — train/dev/test split manager (10–20% / 40–45% / 40–45%) with hard `train ∩ dev ∩ test == ∅` assertion.
  - `alignment.py` — judge refinement loop: run judge over dev split, compute TPR/TNR, surface false-pass + false-fail lists for prompt refinement. Stop when both ≥ 0.85.
  - `correction.py` — `estimate_success_rate(test_labels, test_preds, unlabeled_preds, B=20000)` per the chapter 5 algorithm. Pure-numpy. Returns `(theta_hat, L, U)` where `[L, U]` is the 95% bootstrap CI.
  - `judges/registry.py` — central registry of failure modes + judges + their TPR/TNR thresholds.
- `tests/fixtures/labeled_traces/<failure_mode>/{train,dev,test}.jsonl` — labeled trace splits per failure mode.
- `make test-regression` runs the full suite end-to-end.
- `docs/v2.5.0-spot-review.md` — checkpoint file with 3 paper-review boxes, signed by Jackson before tag.
- Weekly re-alignment job (`make realign`) labels 10 fresh production traces per failure mode, recomputes TPR/TNR, warns if either drops below 0.85.

**Delta.**

The deltas split into two streams that can run partly in parallel:
- **Stream A (Error Analysis & Labeling):** T1, T2, T4a–T4e — produces the labeled trace dataset. Can start in Phase 0; labeling is the longest-pole calendar item (Jackson's time).
- **Stream B (Infrastructure & Judges):** T3, T5, T6, T7, T8, T9, T10, T11, T12 — depends on Stream A's labeled splits being available.

| ID | Task | Stream | Estimate |
|---|---|---|---|
| 6.15.T1 | **Curate 5 canonical fixture topics via the dimension-tuple-query method** (per chapter 3 guidance against generic LLM-prompted generation). Define 3 dimensions (domain, novelty, experiment-requirement). Hand-pick 5 dimension tuples that force coverage. For each tuple, write `topic.txt` + `expected.yaml` (structural assertions) + `reference_paper.bib` (curated bibliography v2.5.0 should rediscover ≥80% of) + `metrics.yaml` for experiment-bearing topics (AUROC/accuracy ranges for the chosen dataset). | A | M |
| 6.15.T2 | **Bootstrap starting trace dataset of 100+ traces.** Sample from `output/` archive (preferred over synthetic per chapter 3); if archive < 100, top up via the dimension-tuple-query method using the 6.15.T1 dimensions. Export each trace's complete record (LLM messages, tool calls, intermediate outputs, final manuscript) to a row in `tests/fixtures/labeled_traces/_raw/traces.jsonl`. | A | M |
| 6.15.T3 | Build `tools/output_assertions.py` with 12–16 atomic code-based assertions (one function each, binary Pass/Fail + reason string). Cover: IMRaD vs sysrev section presence (regex on headings), bibliography ≥20 sources, ≥50% from last 3 years, all DOI-verified, title ≤12 words, abstract 150–300 words, page count ∈ [8, 30], every figure has caption + body reference, every numeric claim has trace token OR citation, no orphan paragraphs (any paragraph with zero citations + zero trace tokens), cascade verdict ≠ reject, no `[MATERIAL GAP]` flags. Each assertion has a unit test in `tests/unit/tools/test_output_assertions.py`. | B | L |
| 6.15.T4a | **Open coding pass.** Read 100+ traces from T2 in a single sitting. For each, write a freeform first-failure annotation + a binary acceptable/unacceptable judgment in a 4-column spreadsheet (`trace_id`, `summary`, `first_failure_note`, `acceptable`). Continue until ≥20 problematic traces are labeled and new failure types stop appearing (theoretical saturation). Use top-down lenses (hallucination, fabrication, citation issues, structural gaps) when stuck. **Single labeler (Jackson)** per chapter 3's recommended efficiency path — no inter-annotator agreement needed. | A | L |
| 6.15.T4b | **Axial coding.** Take all open codes from T4a + the trace excerpts. Use an LLM to propose preliminary failure-mode groupings (paste codes + traces, ask for clusters with names + 1-line definitions). **Critically review and edit** the LLM's proposed taxonomy: rename, split (hallucinated property features vs hallucinated user actions are different), or merge categories. Lock the taxonomy at 6 named failure modes. Write `docs/evaluation/failure-modes.md` with definitions + 3+ representative trace excerpts per mode. | A | M |
| 6.15.T4c | **Structured labeling pass.** Go back through all 100+ traces from T2. For each trace, mark 1/0 per failure mode (pivot-table style, one column per mode in the labeled JSONL). Compute prevalence per failure mode. Output: `tests/fixtures/labeled_traces/_raw/labeled.jsonl` with all 6 failure-mode columns populated. | A | M |
| 6.15.T4d | **Iteration round 2.** Per chapter 3: 2–3 iteration rounds typical. After T4c, identify any failure mode with < 30 Pass examples or < 30 Fail examples (chapter 5 minimum for reliable TPR/TNR). For under-represented modes, sample additional traces (synthetic via T2 method targeting that mode, or additional production traces). Re-label. Refine taxonomy if a new edge case surfaces. Lock when each mode has ≥ 30 Pass + ≥ 30 Fail. | A | M |
| 6.15.T4e | **Train/dev/test split.** Per failure mode, split the labeled JSONL into `train.jsonl` (10–20%), `dev.jsonl` (40–45%), `test.jsonl` (40–45%) under `tests/fixtures/labeled_traces/<failure_mode>/`. Assert the three sets are disjoint via trace_id. Stratify so each split has ≥ 30 Pass + ≥ 30 Fail. | A | S |
| 6.15.T5 | Build `src/academic_pipeline/evaluation/splits.py`: `load_split(failure_mode, split_name)` returns the JSONL with hard `train ∩ dev ∩ test == ∅` assertion. Build `alignment.py`: `run_judge_on_split(judge, split) → (TPR, TNR, false_passes, false_fails)`. | B | M |
| 6.15.T6 | **Implement the 6 LLM-as-Judge evaluators** following chapter 5's prompt template (clear task, precise Pass/Fail definitions, few-shot from train split ONLY, JSON `{reasoning, answer}` output, **single failure mode per judge** — no multi-criteria judges). Iteratively refine each judge using `alignment.py` against its **dev** split: write baseline → measure TPR/TNR → inspect disagreements → swap few-shot examples + clarify wording → repeat until TPR ≥ 0.85 AND TNR ≥ 0.85. **Lock prompts before measuring on test split.** Anti-overfit: never use a dev/test trace as a few-shot example. | B | L |
| 6.15.T7 | Add `judgy>=0.1` from PyPI as a dev dependency (it is a real public package — github.com/ai-evals-course/judgy — and only depends on numpy, so no need to port). Wrap its `estimate_success_rate(test_labels, test_preds, unlabeled_preds, B=20000)` in `correction.py` with our error-code namespacing + a typed return dataclass. Unit tests: synthetic 80% true rate recovered ±0.03, CI width narrows as TPR + TNR → 1, raises on degenerate judge (`TPR + TNR ≤ 1`). | B | S |
| 6.15.T8 | *(removed — A/B comparator was overkill for a single-author project; folded into T10 spot-review as a side-by-side eyeball on one of the 3 papers)* | — | — |
| 6.15.T9 | Wire `make test-regression` to: (Phase A) run all structural assertions on each fixture topic, fail if any returns Fail; (Phase B) load each judge's locked prompt, run on the failure mode's test split, fail if TPR < 0.85 or TNR < 0.85; (Phase C) run all 6 judges on a rolling sample of latest 50 production runs, compute bias-corrected pass rate + 95% CI per failure mode, fail if any CI lower bound < 0.70. | B | M |
| 6.15.T10 | Create `docs/v2.5.0-spot-review.md` template — 3 placeholder paper-link sections, each with: (a) link to `output/<run_id>/03-writing/manuscript.pdf`, (b) checklist of 8 things to spot-check (thesis present, IMRaD or sysrev structure, no fabricated numbers, citations resolve, abstract scoped, figures captioned, methodology defensible, conclusions supported), (c) Jackson's signature line. **One of the 3 papers must be on a topic that also has a v2.4.0 baseline run available; Jackson eyeballs the two side-by-side and notes which is better.** §11 release plan blocks v2.5.0 tag until all 3 boxes checked + signed. | B | XS |
| 6.15.T11 | Document the full evaluation lifecycle in `docs/architecture/evaluation.md`: error-analysis methodology (chapter 3 steps), failure-mode taxonomy, judge construction (chapter 5 steps), TPR/TNR + bias correction, bootstrap CI interpretation, regression suite operation, weekly re-alignment, when to add a new failure mode. **Include the chapter's known biases** (position, verbosity, self-enhancement) as caveats and document mitigation: single-output evaluation per call (no side-by-side comparison → no position bias), explicit "ignore length" instruction in judge prompts (verbosity bias), use a different model family for judging than for generating where possible (self-enhancement bias). ≤500 lines. | B | M |
| 6.15.T12 | Weekly re-alignment job. `make realign`: pulls 10 fresh production traces per failure mode, runs each judge, surfaces traces where judge predicted Pass but Jackson would label Fail (or vice versa) for human re-labeling. Re-computes TPR/TNR on the full test split + new traces. Emits warning if TPR or TNR drops below 0.85. Per chapter 5: "production data can drift; re-run alignment regularly." Documented as a weekly cron candidate; manual invocation acceptable for v2.5.0. | B | S |
| 6.15.T13 | **Anti-overfit CI guard.** A check in `make check` that asserts no trace_id appears in BOTH a judge's prompt few-shot examples AND its dev/test JSONL splits. Fails the build on overlap. Per chapter 5: "any trace used in the prompt must be excluded from the evaluation set." | B | S |

**Verification.**
```bash
# Phase A: structural assertions over all fixtures
uv run python -m academic_pipeline.evaluation.regression --fixtures tests/fixtures/golden/ --strict && \
# Phase B: LLM-as-Judge alignment held on test splits (TPR/TNR ≥ 0.85 each)
uv run python -m academic_pipeline.evaluation.alignment --judges all --on test --min-tpr 0.85 --min-tnr 0.85 && \
# Phase C: bias-corrected true pass rate over latest 50 production runs (CI lower ≥ 0.70 per mode)
uv run python -m academic_pipeline.evaluation.estimate --runs latest:50 --judges all --min-ci-lower 0.70 && \
# Phase D: anti-overfit guard
uv run python -m academic_pipeline.evaluation.overlap_check && \
# Phase E: human signoff present (3 boxes checked in spot-review file, one is v2.4.0/v2.5.0 side-by-side)
test "$(grep -c '^- \[x\]' docs/v2.5.0-spot-review.md)" = "3"
```

**HALT gates for autonomous loops.** This is the only component an autonomous loop CANNOT close on its own. Tasks **T4a, T4b, T4c, T4d, T4e** require Jackson's labeling judgment (per chapter 3: domain experts must label; outsourcing to non-experts produces superficial taxonomy). Task **T6** requires Jackson's review of judge disagreements during refinement. Task **T10** requires Jackson's signature on each paper. The loop should: prepare the labeling spreadsheet, surface trace samples, draft taxonomies + judge prompts as proposals, then **HALT and surface to Jackson** for the human-judgment steps. Do not synthesize labels. Do not check the spot-review boxes. Do not lock failure modes without Jackson's review.

**Common pitfalls (do not commit any of these).** From chapter 3 and chapter 5, ported into our context:
- ❌ Generic synthetic queries ("Generate 5 paper topics for an academic pipeline") — produces repetitive coverage. Use dimension-tuple-query method (T1).
- ❌ Skipping open coding for off-the-shelf metrics ("hallucination", "instruction-following"). Failure modes must come from reading our actual traces.
- ❌ Likert scales (1–5) in early annotation — noisy without detailed rubric. Use binary Pass/Fail (acceptable / unacceptable).
- ❌ Multi-criteria single judge ("rate tone + content + next-steps in one Pass/Fail"). One failure mode per judge.
- ❌ Dev/test traces appearing as few-shot examples in their judge's prompt — overfits TPR/TNR and inflates apparent quality. T13 enforces this.
- ❌ Freezing the failure-mode taxonomy too early. Expect 2–3 iteration rounds (T4d).
- ❌ Outsourcing labeling to non-domain experts. Jackson labels.
- ❌ Reporting dev-split TPR/TNR as the judge's quality. Always measure on the held-out test split, after locking the prompt.

---

## 7. Deferred Work

### 7.1 Spec 9 — Cross-run memory (AgentRxiv port)

**Status.** Not started. Explicitly out of scope for v2.5.0.

**Why deferred.** Per `2026-05-03-cross-run-memory-design.md` and the spec roadmap: cross-run memory is only useful once enough runs exist to learn from. The author has not yet shipped 10 papers through the new pipeline. Building cross-run memory before a meaningful corpus exists is premature optimization.

**Trigger condition.** When `output/` contains ≥10 successful pipeline runs (i.e., `find output -name 'manuscript.pdf' | wc -l >= 10`), unblock this spec. At that point, write a v2.6.0 PRD addendum or a v3.0.0 PRD that includes Spec 9 in §6.

**Autonomous loop directive.** **Do not start work on Spec 9.** If you find yourself with no in-scope work remaining, halt and surface the gap. Do not opportunistically scope into deferred work.

---

## 8. External Dependencies and Blockers

| Dependency | Used by | Failure mode | Mitigation |
|---|---|---|---|
| Anthropic API (Opus 4.7) | All 38 agents | LLM proxy 1h+ wedged-in-recv | §6.6 4-layer recovery |
| Anthropic API rate limits | All agents | 429 responses under burst | `tool_call_delay_seconds: 10` default; PydanticAI built-in retries (`anthropic_max_retries: 3`) |
| Exa API | Bibliography search, dataset discovery (§6.1, §6.2) | API down → no sources | Hard-fail bibliography node; no fallback search engine wired |
| CrossRef API | DOI verification (§6.7.T2) | API down → DOI gate fails | `--allow-unverified-dois` escape-hatch flag (to be added in 6.7.T2) |
| Semantic Scholar API | Novelty gate (§6.1, Spec 3), point-wise novelty reviewer (§6.4, Spec 4) | API down or rate-limited | `s2_api_key` env var raises rate limit; no fallback wired |
| Pydantic Logfire | Tracing | Service down → tracing dropped | Pipeline continues; events.jsonl is the durable log |
| Docker (optional) | Experiment subgraph sandboxing (§6.2) | Docker not installed → subprocess fallback | `experiment_use_docker: false` config |
| tectonic | PDF compilation (§6.7) | Binary missing → render fails | Documented in INSTALL.md as required dep |
| pandoc | Markdown→LaTeX (§6.7) | Binary missing → render fails | Documented in INSTALL.md |
| IEEEtran / ACL `.cls` files | Template rendering (§6.7) | Missing files → tectonic fail | Bundled in `templates/pandoc/` (IEEEtran); ACL to be bundled in §6.7.T1 |
| `authors.yaml` | DOI gate, manuscript metadata (§6.7) | Missing file → render aborts | §6.7.T3 enforces this and emits clear error |
| Hugging Face datasets | Experiment subgraph (§6.2) | Dataset removed or rate-limited | Email alert via §6.2 SMTP config; pipeline pauses for user-provided data |
| MLflow | Experiment tracking (§6.2) | Local SQLite, no external dep | n/a |
| DVC | Dataset versioning (§6.2.T4) | Binary missing | Documented in INSTALL.md after §6.2.T4 lands |

**Verification commands that depend on infrastructure not yet built:**
- §6.6.T4: `events.jsonl` `recovery_event` records depend on §6.8.T1 + §6.8.T2 (event types defined and rendered). Sequence accordingly.
- §6.7 verification: depends on `manuscript.pdf` being produced, which depends on §6.3 + §6.10 (traceability `full` mode + dialogue) being green. Run §6.7 verification only after §6.10 verification.
- §6.2 verification: end-to-end smoke depends on LLM proxy being up. CI may need to mock the agent layer for the integration smoke.

---

## 9. Risks and Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Phase 2 wirings reveal that Phase 1 specs misjudged the integration surface (e.g. cascade verdict + editorial synthesis prompt collide) | M | M | Each Phase 2 task lands behind a `legacy_*` flag flip; rollback is one config edit. |
| R2 | SCI peer review still rejects v2.5.0 papers despite all 8 specs landed | M | H | Track per-rejection failure modes in a new memory entry; add Spec 10 candidates rather than re-litigating Phase 2. |
| R3 | Dagster template Stages 3–6 (§6.2.T1–T4) are large lifts; estimated effort underestimates real complexity | M | M | Land one stage at a time; each stage is independently shippable behind `problem.type`. |
| R4 | `traceability_mode: full` default-on uncovers fabrication patterns the Phase 1 partial mode missed | H | M | Phase 1 of Spec 1 already covers ~85% of patterns per progress memory; remaining 15% surface as `TRC-*` errors which are debuggable, not silent. |
| R5 | React dashboard v2 (§6.8.T5) is the only UI work in v2.5.0 and may slip | L | L | Dashboard v1 keeps working; v2 is non-blocking for paper generation. |
| R6 | Spec 9 (deferred) feels small enough that an autonomous loop opportunistically scopes it in | M | M | Explicit non-goal N7 + §7 directive; no Spec 9 task ID exists in §6 to anchor against. |
| R7 | LLM proxy degrades further (e.g. shorter idle limit) and breaks bounded_run defaults | L | H | `llm_timeout_seconds` already configurable; watchdog 75s threshold tunable. |
| R8 | Anthropic deprecates `anthropic_effort: max` setting | L | H | Out of project's control; mitigation = swap to next-tier setting; no other dependency. |
| R9 | DOI gate (§6.7.T2) rejects too aggressively and blocks builds for legitimate papers | M | M | `--allow-unverified-dois` escape hatch; default still gates strictly. |
| R10 | State-file schema versioning (§6.9.T1) breaks all in-flight resumes when v2.5.0 ships | H (intentional) | M | Documented in CHANGELOG; cleanup script (§6.9.T5) provided; users run `make resume` once on each in-flight run before upgrading. |

---

## 10. Sequencing (dependency-ordered execution plan)

This section linearizes §5.5 into a phase-by-phase task plan. Autonomous loops should derive their `fix_plan.md` from this section. Components inside the same phase are independent and may be parallelized across separate worktrees / agent sessions.

### Phase 0 — Foundation + Error-Analysis kickoff (no prerequisites)

Land the config + SDK substrate AND start the labeling work, since labeling 100+ traces is the longest-pole calendar item for §6.15.

**Foundation stream:**
1. `6.12.T6` — version unification (VERSION + pyproject + README + check script). Do this **first** so the rest of v2.5.0 lands under a coherent version.
2. `6.12.T7` — declared-but-unused dependency decision (remove fastapi/uvicorn/mcp/dbos extras unless justified). Land before deps drift further.
3. `6.12.T1` — bundle SCI flag flips (configurable but defaults still false until each subsystem lands its Phase 2)
4. `6.12.T5` — per-node quality threshold map in PipelineConfig
5. `6.12.T2` — `Pipeline.observe(callback)` SDK surface
6. `6.12.T8` — skill packs documented (`docs/architecture/skills.md`)
7. `6.12.T9` — `docs/README.md` index refresh
8. `6.12.T3` + `6.12.T4` — examples + sdk.md doc

**Error-analysis stream (run in parallel; this is Jackson's calendar time, not the loop's):**
9. `6.15.T1` — curate 5 fixture topics via dimension-tuple-query method
10. `6.15.T2` — bootstrap 100+ trace dataset from `output/` archive (loop can prepare; no labels yet)
11. `6.15.T4a` — open coding pass (Jackson)
12. `6.15.T4b` — axial coding to lock 6 failure-mode taxonomy (Jackson reviews LLM-proposed clusters)
13. `6.15.T4c` — structured 1/0 labeling per failure mode across all 100+ traces (Jackson)
14. `6.15.T4d` — iteration round 2; top up under-represented modes to ≥30 Pass + ≥30 Fail each (Jackson)
15. `6.15.T4e` — train/dev/test split per failure mode

**Verification gate:** `uv run pytest tests/unit/test_config.py tests/unit/sdk/ -x -q && uv run python tools/check_version_consistency.py` green AND `tests/fixtures/labeled_traces/<each_failure_mode>/{train,dev,test}.jsonl` exists with disjoint sets and ≥30 Pass + ≥30 Fail each.

### Phase 1 — Recovery, Persistence, Quality Gate, CI (parallel)

Four independent components. Spawn four sub-sessions or run sequentially.

| Stream | Tasks |
|---|---|
| Recovery (§6.6) | `6.6.T1` → `6.6.T3` → `6.6.T4` (T2 paired with §6.8.T1) |
| Persistence + AgentCache (§6.9) | `6.9.T1` → `6.9.T2` → `6.9.T5` → `6.9.T6` |
| Quality Gate (§6.11) | `6.11.T1` (paired with §6.8.T2) → `6.11.T2` → `6.11.T4` → `6.11.T6` |
| CI / Release (§6.14) | `6.14.T2` (audit publish.yml first — informs everything else) → `6.14.T3` → `6.14.T4` → `6.14.T1` → `6.14.T5` → `6.14.T6` |

**Verification gate:** all four component verification commands green.

### Phase 2 — Traceability + Dashboard + Events + Observability (parallel)

Three streams. Observability rides on Dashboard+Events for the new event types.

| Stream | Tasks |
|---|---|
| Dashboard + Events (§6.8) | `6.8.T1` → `6.8.T2` → `6.8.T3` → `6.8.T4` → `6.8.T6` (T5 dashboard v2 can defer) |
| Traceability (§6.10) | `6.10.T2` → `6.10.T3` → `6.10.T4` → `6.10.T5` → `6.10.T6` → `6.10.T7` → `6.10.T8` |
| Observability (§6.13) | `6.13.T2` → `6.13.T3` → `6.13.T1` (paired with §6.8.T1) → `6.13.T4` → `6.13.T5` |

**Note:** `6.10.T1` (dialogue helper) pairs with `6.3.T9` and `6.9.T3` — land together in Phase 4.

**Verification gate:** `uv run pytest tests/unit/runtime/test_dashboard.py tests/unit/traceability/ tests/unit/test_observability.py -x -q` green.

### Phase 3 — Rendering

Single stream, depends on Persistence (§6.9) and soft-depends on Traceability (§6.10).

`6.7.T1` (land in-flight uncommitted) → `6.7.T2` (DOI gate) → `6.7.T3` (authors.yaml) → `6.7.T4` (title constraint) → `6.7.T5` (matplotlib pub style) → `6.7.T6` (ACL e2e) → `6.7.T7` (docs) → `6.7.T8` (delete broken script) → `6.7.T9` (ACL anthology citation style).

**Verification gate:** end-to-end `manuscript.pdf` produced via §6.7 verification command.

### Phase 4 — Subgraphs that depend on cross-cutting (parallel where possible)

Three subgraphs become buildable now. Research and Integrity in parallel; Experiment can interleave (its Stage 3–6 work is mostly self-contained).

| Stream | Tasks |
|---|---|
| Research (§6.1) | `6.1.T1` → `6.1.T2` → `6.1.T3` → `6.1.T4` → `6.1.T5` → `6.1.T6` → `6.1.T7` → `6.1.T8` → `6.1.T9` |
| Integrity (§6.5) | `6.5.T1` → `6.5.T2` → `6.5.T3` → `6.5.T4` → `6.5.T5` |
| Experiment (§6.2) | `6.2.T1` → `6.2.T2` → `6.2.T3` → `6.2.T4` → `6.2.T7` → `6.2.T8` (T5/T6/T9 in Phase 5) |

**Verification gate:** each subgraph's verification command green.

### Phase 5 — Writing + Review + dialogue + breadth

Depends on everything before. Outputs of Phase 5 become inputs to the §6.15 judges in Phase 6.

| Stream | Tasks |
|---|---|
| Writing (§6.3) | `6.3.T1` (paired with `6.7.T1`, may already be done) → `6.3.T2` → `6.3.T3` → `6.3.T4` → `6.3.T5` → `6.3.T6` → `6.3.T7` → `6.3.T8` → `6.3.T9` (paired with `6.10.T1` + `6.9.T3`) → `6.3.T10` |
| Review (§6.4) | `6.4.T1` → `6.4.T2` → `6.4.T3` → `6.4.T4` → `6.4.T5` → `6.4.T6` → `6.4.T7` → `6.4.T8` → `6.4.T9` |
| Experiment breadth (§6.2 remainder) | `6.2.T5` → `6.2.T6` → `6.2.T9` → `6.2.T10` |
| Dashboard v2 (§6.8.T5) | run any time after Phase 2; non-blocking |

**Verification gate:** full `make check` + `make test-integration` + one end-to-end `make run-experiment` smoke.

### Phase 6 — Output Verification (gates v2.5.0 release)

Depends on Phase 5 outputs (judges score Phase-2 behavior, not Phase-1) AND on Phase 0 labeled splits being available.

| Stream | Tasks |
|---|---|
| Infrastructure (§6.15 Stream B) | `6.15.T3` (assertion library) → `6.15.T5` (splits + alignment) → `6.15.T7` (Rogan-Gladen + bootstrap CI) → `6.15.T13` (anti-overfit guard) |
| Judges (§6.15 Stream B continued) | `6.15.T6` (build + refine 6 judges against dev split until TPR/TNR ≥ 0.85; lock prompts) |
| Regression assembly (§6.15 Stream B continued) | `6.15.T9` (regression suite assembly — Phases A/B/C only) |
| Re-alignment + docs (§6.15 Stream B continued) | `6.15.T11` (evaluation.md) → `6.15.T12` (`make realign`) |
| Spot-review checkpoint (§6.15) | `6.15.T10` (template; one paper must be v2.4.0/v2.5.0 side-by-side) → **HALT for Jackson signoff** |

**Verification gate:** §3.3 gates 9–12 all green:
- (9) `make test-regression` Phase A green on all 5 fixtures
- (10) every judge TPR ≥ 0.85 AND TNR ≥ 0.85 on its test split
- (11) bias-corrected pass rate per failure mode has CI lower ≥ 0.70 over 50 production runs
- (12) Jackson signs all 3 boxes in `docs/v2.5.0-spot-review.md` (one is a v2.4.0 vs v2.5.0 side-by-side eyeball)

---

## 11. Release Plan

| Milestone | Date target | Gate criteria |
|---|---|---|
| v2.5.0-alpha1 | end of Phase 2 | Config substrate + recovery hardening + traceability Phase 2 in place. `make check` green. No flag flips yet. |
| v2.5.0-alpha2 | end of Phase 3 | Rendering pivot complete. `make run` produces a valid ACL-template PDF on a sample topic. DOI gate, authors.yaml, title constraint live. |
| v2.5.0-beta1 | end of Phase 4 | Research + Integrity + Experiment Stages 3–6 wired. Phase 1 SCI flags still default false. Beta runs can flip via `configs/dev.yaml`. |
| v2.5.0-rc1 | mid Phase 5 | Writing + Review Phase 2 wirings shipped, all SCI flags flipped to `true` in `configs/default.yaml`. Run a full `make run-experiment` against a sample topic and verify cascade verdict appears, persona reviewers fired, traceability `full` mode resolved, ACL template PDF produced. **§6.15 Stream B (judge infrastructure) underway** but TPR/TNR not yet locked. |
| v2.5.0-rc2 | mid Phase 6 | Regression suite Phases A–C green (structural assertions + judge alignment + bias-corrected production estimate). Spot-review file template exists, no boxes checked yet. |
| v2.5.0 final | end of Phase 6 | All §6 deltas marked `[x]` or `[skipped]` with rationale. **All §3.3 gates 1–12 hold** — both code/process gates AND output gates. CHANGELOG entry written. README badges bumped. `examples/` updated. **Jackson has signed off on 3 sample papers in `docs/v2.5.0-spot-review.md`** (one of which is a v2.4.0 vs v2.5.0 side-by-side eyeball). Tag pushed only after all of the above. The SCI verdict on a submitted paper comes after release; the release does not depend on it. |

**Calendar estimate.** Phases 0–6 sum to roughly 9–12 calendar weeks at one engineer/agent equivalent. Phase 0's labeling sub-stream is the longest pole (Jackson's time, not the loop's — typically 2–3 weeks of part-time labeling for 100+ traces with axial-coding iteration). Phase 6 verification adds about 1 week at the end. Parallelization can compress to 6–8 weeks if Phases 1, 2, and 4 each run multiple streams concurrently AND Phase 0 labeling starts immediately.

**Tag-and-publish flow.** When all gate criteria are met (including §3.3 gates 9–12 and Jackson's signed spot-review):

```bash
# Pre-flight 1: version coherence
uv run python tools/check_version_consistency.py     # added in §6.12.T6

# Pre-flight 2: full regression suite green (output gates 9–11)
make test-regression

# Pre-flight 3: human signoff present (output gate 12)
test "$(grep -c '^- \[x\]' docs/v2.5.0-spot-review.md)" = "3" || { echo "Jackson has not signed off on 3 papers — DO NOT TAG"; exit 1; }

# Tag (triggers .github/workflows/publish.yml — see §6.14.T2 for what it does)
git tag -a v2.5.0 -m "v2.5.0 — see CHANGELOG.md"
git push origin v2.5.0
```

The `publish.yml` workflow is currently 332B and **unaudited**; §6.14.T2 audits it before the v2.5.0-rc1 tag and updates `docs/architecture/release.md` with the verified behavior (PyPI publish, GitHub Release, both, neither). Do not push v2.5.0 tags until §6.14.T2 is complete AND the spot-review file is signed.

**No Phase 7.** v2.5.0 is the last release that ships Phase 1 → Phase 2 wirings. Spec 9 (cross-run memory) is explicitly v2.6.0+ work — gated on 10 papers shipped through v2.5.0+ pipeline (per §7).

---

## 12. Glossary

**Subgraph** — a `pydantic_graph.Graph` of `BaseNode[StateT, DepsT, RunEndT]` dataclasses. The pipeline composes 5 of them. Each lives in `src/academic_pipeline/<subgraph>/graph.py`.

**Node** — one `BaseNode` subclass; the unit of graph progression and resume.

**Agent** — a PydanticAI `Agent` instance loaded from a YAML spec via `Agent.from_file()`. Defined in `<subgraph>/specs/*.yaml`, registered in `<subgraph>/agents.py`.

**PromptedOutput** — PydanticAI wrapper around structured-output models that is Thinking-compatible. All structured-output agents in this pipeline use it.

**Evaluator-optimizer** — per-node loop: produce → score against rubric → if below threshold, refine → repeat up to `max_node_iterations` (default 2).

**Independent verifier** — Opus 4.7 with `anthropic_effort: max` and `max_tokens: 128000`. Second-pass review of research claims (text) or figures (VLM).

**Hard veto** — pattern-based block in `runtime/hard_vetos.py`. Independent of evaluator score. Two registered at HEAD: `no_placeholder_tokens` (7 patterns + `[PENDING: ...]` sanctioned exception) and `no_bare_latex_commands` (≈82 math whitelist). When ANY veto fires, `apply_hard_vetos` forces `verdict = "NEEDS_IMPROVEMENT"`, preserves `scores` unchanged (informational), sets `weakest_dimension = "hard_veto"` (sentinel — NOT a real rubric dimension), and prepends `"HARD VETO: "` to feedback. Loop extending this layer MUST: (a) preserve `[PENDING: ...]` carve-out, (b) keep scores untouched, (c) treat `weakest_dimension == "hard_veto"` as structural failure in downstream consumers.

**`anthropic_effort: max`** — provider-specific Anthropic effort tier above `xhigh`. Used for the 7 reviewer/verifier agents.

**SCI** — Science Citation Index. The journal-indexing standard the author's papers target.

**Phase 1** — for an SCI spec, the version that is shipped behind a config flag, default off, additive. Existing behavior preserved.

**Phase 2** — for an SCI spec, the version that flips the flag default to `true`, replaces the legacy codepath it shadows, and removes (or behind-`legacy_*`-flags) the prior code.

**Trace token** — `⟨num:label⟩` placeholder in agent output (verified pattern at `traceability/_patterns.py:11`: `r"⟨num:(?P<label>[a-zA-Z_][a-zA-Z0-9_]*)⟩"`; the angle brackets are Unicode `⟨` U+27E8 and `⟩` U+27E9, NOT ASCII `<` `>` or double-curly `{{ }}`) that resolves to a numeric value from `ExperimentResults` at render time. Spec 1.

**ContextSpec** — per-agent context-build descriptor used by the traceability layer. Currently centralized; per-agent rollout is part of §6.10 deltas.

**Cascade** — three-stage reviewer composition (A: numerical grounding, B: novelty, C: methodology). Spec 6.

**Persona reviewer** — adversarial reviewer prompted as a specific named persona (senior_gatekeeper, applied_practitioner, methodology_purist). Spec 5.

**CoI / Chain-of-Ideas** — literature-arc extractor that produces a development chain + thesis, replacing the bib-ref-as-node KG. Spec 2.

**PRISMA-trAIce** — 12-item ethics checklist for AI-generated research. Spec 8.

**Dagster template** — the workspace at `templates/dagster-experiment/` that the experiment subgraph copies into `output/<run-id>/02-experiment/` and runs against. Replaces the old monolithic `experiment.py`.

**`config.yaml` (workspace)** — the single declarative file the `config_writer` agent emits to drive the Dagster template. Validated against `pipeline/config_models.py::ExperimentConfig`.

**MLflow run ID** — per-experiment identifier captured by the Dagster template via `mlflow.autolog()`. Cited in the manuscript.

**DVC** — dataset versioning tool used to pin HuggingFace dataset hashes per run (Stage 6).

**`events.jsonl`** — append-only log under `output/<run-id>/`. Single source of truth for pipeline progress. Dashboard is a pure renderer over it.

**`heartbeat.txt`** — file under `output/<run-id>/` updated every 30s by a daemon thread. L3 of the recovery system.

**Watchdog** — sibling subprocess to the pipeline that polls `events.jsonl` and `heartbeat.txt` mtimes; kills + optionally resumes on stall. L4 of the recovery system.

**3-strikes** — watchdog escalation: if 3 consecutive recoveries fail to advance `events.jsonl`, abort the supervisor.

**`AgentMessageCache`** — per-agent persistence of PydanticAI `ModelMessage` history to `.pipeline_runs/<thread-id>_<agent>_cache.json`. Enables multi-turn dialogue resume across crashes.

**`legacy_*` flag** — escape-hatch config flag added when a Phase 2 wiring deletes a default codepath. Allows users to revert by flipping the flag.

**LLM proxy** — the proxy through which Anthropic API calls are routed. Source of the 1h+ wedged-in-recv failures the recovery system addresses.

---

## 13. PydanticAI Conventions and Anti-Patterns

This section codifies the PydanticAI patterns the codebase uses today and the anti-patterns autonomous loops MUST NOT introduce. Verified against PydanticAI docs as of 2026-05-06 and against the actual codebase under `src/academic_pipeline/`.

### 13.1 Verified codebase patterns (do these)

| Pattern | Where used | Snippet |
|---|---|---|
| `from pydantic_ai import Agent, PromptedOutput` | every `<subgraph>/agents.py` | `output_type=PromptedOutput(MyModel)` |
| YAML spec loaded via `Agent.from_file()` | every `<subgraph>/agents.py` | `Agent.from_file('research/specs/synthesis.yaml')` |
| `Thinking` capability for sub-max effort | most agent YAMLs | `capabilities:\n  - Thinking: { effort: xhigh }` |
| `model_settings.anthropic_effort: max` for verifier tier | `independent_verifier.yaml`, `figure_verifier.yaml`, all 7 reviewer agents | `model_settings:\n  anthropic_effort: max\n  max_tokens: 128000` |
| Per-agent `output_validator(fn)` registration | `research/agents.py::agents["ethics_review"].output_validator(validate_ethics_checklist)` | post-construction registration after `Agent.from_file` |
| `ModelMessagesTypeAdapter` for message persistence | `tools/agent_cache.py::AgentMessageCache` | `ModelMessagesTypeAdapter.validate_python(json_obj)` |
| `message_history=` parameter on `agent.run()` | judge loop, dialogue helper | `await agent.run(prompt, message_history=cache.load())` |
| `TestModel` via `agent.override(model=TestModel(custom_output_text=json))` | `tests/conftest.py::make_test_model(output: str = "Test output.")` (verified signature) | always inside `with agent.override(...)` block |
| **`make_structured_test_model(model_cls, seed=0)`** for PromptedOutput agents | `tests/conftest.py:59` (verified) | uses `_JsonSchemaTestData` from `pydantic_ai.models.test` to generate valid JSON conforming to the agent's `PromptedOutput(MyModel)` schema |
| **`make_union_test_model(model_cls, kind=None)`** for union output types | `tests/conftest.py:90` (verified) | for agents with `output_type=PromptedOutput(A \| B)` — wraps the JSON with the discriminator |
| **`make_field_overrides_test_model(...)`** for partial schema overrides | `tests/conftest.py:76` (verified) | when the test wants to assert specific field values rather than the full Pydantic-default JSON |
| `traced_agent_run(agent, ...)` wrapper | every agent invocation | wraps `bounded_agent_run` (L2 recovery) + Logfire span enrichment |
| `Agent` import path: `from pydantic_ai import Agent` | universal | not `from pydantic_ai.agent import Agent` |
| Model string with provider prefix | universal | `"anthropic:claude-opus-4-7"` |
| **`pydantic_ai_skills.SkillsCapability`** for skill-pack-aware agents | `research/agents.py:14`, `review/agents.py:14` (verified at HEAD) | `from pydantic_ai_skills import SkillsCapability; capabilities=[SkillsCapability(skills_dirs=SKILLS_DIRS), ...]` |
| **`AnthropicCompaction(token_threshold=...)`** for context compaction | `research/agents.py`, `review/agents.py`; threshold from `DEFAULT_CONFIG.compaction_token_threshold` (default 800000) | `from pydantic_ai.models.anthropic import AnthropicCompaction; _COMPACTION = AnthropicCompaction(token_threshold=DEFAULT_CONFIG.compaction_token_threshold)` |
| `throttle_hooks` from `runtime/throttle.py` as a capability | every agent in research + review registries | `capabilities=[throttle_hooks, _COMPACTION]` — passed as a Hooks instance. **Module-level singleton** at `runtime/throttle.py:76` (shared call counter across ALL agents in process — `call_count` is GLOBAL across the entire pipeline, NOT per-agent; verified ralph-74). For per-test independent counters, use the factory `make_throttle_hooks()` which builds a fresh closure-scoped counter (line 29). Throttle skips first call (`call_count <= 1`), applies `DEFAULT_CONFIG.tool_call_delay_seconds` (default 10s) starting from call #2. **`delay` is fetched FRESH each call** from `DEFAULT_CONFIG.tool_call_delay_seconds` (NOT cached at module load — config can be mutated mid-run). **`delay <= 0` skips the sleep** (config can disable throttle entirely without removing the hook). Uses `asyncio.sleep` (NOT `time.sleep` — would block the event loop). Logs at `logger.debug` (not info/warning) so production logs aren't flooded. **Three hook handlers registered (verified line signatures)**: `before_model_request(_ctx: RunContext[object], request_context: ModelRequestContext) -> ModelRequestContext` (throttle, returns context unmodified), `run_error(ctx: RunContext[object], *, error: BaseException)` (log via `logger.error` with `type(error).__name__` + `ctx.retry`, then `raise error`), `model_request_error(ctx: RunContext[object], *, request_context: ModelRequestContext, error: Exception)` (log via `logger.warning` then `raise error`). **`# type: ignore[return-type]` on both error hooks** — they MUST `raise` not return; the type stub expects None but Pydantic's protocol expects ModelRequestContext, by design. Loop must NOT swap `BaseException`/`Exception` types — `run_error` catches `BaseException` (KeyboardInterrupt, SystemExit included for clean shutdown logging), `model_request_error` catches only `Exception` (lower-priority retryable failures). **Stale docstring** at `throttle.py:1` still says "Vertex AI quota protection" but codebase uses Anthropic — cosmetic-only fix candidate, no behavioral impact. |

### 13.2 Anti-patterns the loop MUST NOT introduce

These are mistakes Claude/Codex commonly make with PydanticAI. Getting any of these wrong produces silent failures or confusing errors that won't be caught by `pytest` until production.

| ❌ Anti-pattern | ✅ Correct | Why it matters |
|---|---|---|
| `@agent.tool` without `RunContext` first param | Use `@agent.tool` only when you need ctx; else `@agent.tool_plain` | Runtime error on tool call |
| `@agent.tool_plain` WITH `RunContext` first param | Switch to `@agent.tool` | Runtime error on tool call |
| Model string without provider prefix (`"claude-opus-4-7"`) | `"anthropic:claude-opus-4-7"` | PydanticAI cannot resolve the provider |
| Setting `agent.model = TestModel()` directly in tests | `with agent.override(model=TestModel()):` | Direct assignment leaks across tests |
| `output_type` union including `str` when forced structured output is required | Omit `str` from the union | Model can return plain text and skip the structure |
| `hooks.on.on_run_error` (doubled `on_`) | `hooks.on.run_error` | Hook never fires |
| `history_processor=...` (singular) | `history_processors=[...]` (plural list) | Silently ignored |
| Per-call `output_validators=[...]` arg to `agent.run()` | `agent.output_validator(fn)` post-construction registration | The codebase notes this in `research/agents.py:138` — per-call output_validators not accepted |
| Using `anthropic_thinking={'type': 'enabled', 'budget_tokens': N}` on Opus 4.7 | Adaptive thinking is now the default on Opus 4.6+; do not pass `budget_tokens` (REMOVED on 4.7) | Hard error on Opus 4.7 |
| Directly calling `agent.run()` outside `traced_agent_run` / `bounded_agent_run` | `await traced_agent_run(agent, ...)` | Bypasses L2 recovery (8-min effective cap via `_AGENT_RUN_TIMEOUT_S = 480.0`; the `bounded_agent_run` direct-call default of 900s is reserved for the 3 long-running evaluator paths) and Logfire enrichment |
| Inventing tool names not in the registered tool registry | Always reference an explicit tool function or YAML-declared capability | Causes "Invalid Tool Usage" failure mode (one of §6.15's 6 named modes) |
| Multi-criteria single LLM-as-Judge prompt ("rate tone + content + next-steps") | One failure mode per judge, binary Pass/Fail | Per chapter 5; ambiguity collapses TPR/TNR |
| Using dev/test traces as few-shot examples in a judge prompt | Few-shot strictly from the train split (`6.15.T13` enforces) | Inflates apparent TPR/TNR |
| Likert 1–5 scale in early labeling | Binary Pass/Fail | Per chapter 3; Likert without rubric is noisy |

### 13.3 Anthropic API specifics (verified against Claude API docs 2026)

- **Model identifier:** `claude-opus-4-7` (resolved via `"anthropic:claude-opus-4-7"` model string).
- **Effort levels (Opus 4.7):** `low`, `medium`, `high` (default), `xhigh`, `max`. Set via `model_settings.anthropic_effort` in PydanticAI YAML, which maps to `output_config={"effort": ...}` in the Anthropic Messages API.
- **Adaptive thinking** is the default on Opus 4.6+. PydanticAI exposes via `model_settings.anthropic_thinking={'type': 'adaptive'}` if explicit override needed; the `Thinking: { effort: xhigh }` capability path also resolves to adaptive on Opus 4.6+. **Do not pass `budget_tokens`** — that field is REMOVED on Opus 4.7 and raises a hard error.
- **Token budget for `max` effort:** start at 64k–128k `max_tokens`. The codebase uses 128000 for `independent_verifier` and `figure_verifier`, which is correct.
- **Known interaction:** Anthropic thinking + `tool_choice` forcing tool use raises "Thinking may not be enabled when tool_choice forces tool use" (PydanticAI issue #2425, #3092). The codebase does not force tool_choice — verify any new agent doesn't either.

### 13.4 PydanticAI Capabilities (spec-loadable)

Capabilities marked spec-compatible can appear in YAML; non-serializable ones (custom callables) only in Python. The codebase uses these spec-compatible capabilities:

- `Thinking: { effort: <level> }` — provider-adaptive reasoning.
- `WebSearch` — provider-adaptive search; not currently used (codebase uses Exa direct via `tools/bibliography/exa.py`). **Optional v2.6.0 refactor:** migrate to `pydantic-ai-slim[exa]` for `ExaToolset` consistency. Out of scope for v2.5.0.

### 13.5 Logfire integration (verified)

- `logfire.configure(send_to_logfire="if-token-present")` — graceful degradation when `LOGFIRE_TOKEN` absent.
- `logfire.instrument_pydantic_ai()` — global agent instrumentation (current usage).
- `logfire.instrument_pydantic_ai(agent)` — per-agent targeted instrumentation; **§6.13.T3 should use this** for per-agent tagging instead of global tagging in `traced_agent_run`.
- `logfire.instrument_httpx(capture_all=True)` — captures full request/response bodies. The codebase uses this; surfaces Anthropic SDK payloads end-to-end.

### 13.6 CLI surface (verified ralph-75 against `cli.py` 613 lines)

`python -m academic_pipeline` exposes a `typer.Typer` app with **EXACTLY 7 commands** (verified `@app.command(...)` decorators). Loop adding a command MUST register it here AND update `make-targets` in Makefile AND add a smoke test.

| Command | Decorator | Purpose | Default-divergence gotchas |
|---|---|---|---|
| `run <topic>` | `@app.command()` | Full pipeline (research → write → review → finalize) | `--no-eval` sets `ENABLE_NODE_EVALUATION=false` env var; `--force-experiment` sets `FORCE_EXPERIMENT=true`. **Env-var-based config injection** — loop adding new flags should follow this pattern OR thread through `PipelineConfig`. `--copilot` mutates `pipeline._deps.config` via `model_copy(update={"copilot_enabled": True})` — runtime override of frozen Pydantic config. |
| `resume <thread_id>` | `@app.command()` | Resume crashed run (loads topic from saved state, no re-typing) | **Hardcoded** `db_path = Path(".pipeline_runs/pipeline.sqlite")` (line 247). **Calls PRIVATE method** `persistence._load_pipeline_state_sync(thread_id)` (line 253) — bypasses the async public API. Cleanup candidate: expose `await load_pipeline_state(thread_id)` that the CLI awaits. |
| `dashboard [run_id]` | `@app.command()` | Render events-driven dashboard | `--latest` resolves `output/latest` symlink; `--watch` enters `rich.live.Live` loop with `time.sleep(1.0)` and `KeyboardInterrupt` exit. Loop must NOT replace with `asyncio.sleep` — main thread is sync here. |
| `watchdog <thread_id>` | `@app.command(name="watchdog")` | Standalone watchdog | **CRITICAL CLI/API DEFAULT MISMATCH** (verified ralph-75): CLI default `--poll 15`, but `WatchdogConfig.poll_interval_s = 30`. Programmatic API and CLI have DIFFERENT defaults! Loop running `watchdog` from CLI gets 2× faster polling than `make watchdog`-equivalent direct constructor call. Either harmonize at 30 (recommended — matches API) or document the divergence in `--help`. `--max-idle 600` matches WatchdogConfig (verified). |
| `supervised-run <topic>` | `@app.command(name="supervised-run")` | Pipeline + watchdog as siblings | **Forwards ONLY `--force-experiment` and `--copilot`** to wrapped `run` invocation. Does NOT forward `--no-eval`, `--durable`, `--authors`, `--revision`. Loop adding a flag to `run` must ALSO add forwarding logic in `supervised_run_cmd` if the supervised path needs it. |
| `unseal-run <thread_id>` | `@app.command(name="unseal-run")` | SQLite surgery for AbortNode-sealed runs | Most complex command (~180 lines line 401-582). Walks snapshots DESC to find phase node before AbortNode. Maps outer phase → subgraph run_id suffix via 6-entry dict (`ResearchPhaseNode→_research`, `ExperimentPhaseNode→_experiment`, `WritePhaseNode→_write`, `PreIntegrityNode→_pre_integrity_0`, `ReviewPhaseNode→_review`, `FinalIntegrityNode→_final_integrity_0`). **CRITICAL**: updates BOTH `status` column AND embedded `data_json["status"]` field (lines 542-549) — pydantic-graph reads JSON via TypeAdapter, column-only update is SILENTLY IGNORED. Loop adding new SQLite-surgery commands MUST update both surfaces. Has `--dry-run` and `--delete-terminal-snapshots/--keep-terminal-snapshots` toggles. |
| `supervised-resume <thread_id>` | `@app.command(name="supervised-resume")` | Resume crashed run + watchdog | Wraps `supervised_run(thread_id, ...)` — supervisor accepts thread_id as first arg either as topic OR resume signal (polymorphism). Loop must keep this contract or `supervised_run` callsite signature breaks. |

**`_init` 6-step setup** (verified line 34-79): (1) `configure_ssl()` ALWAYS first, (2) `os.environ` assignments for `ENABLE_NODE_EVALUATION` / `FORCE_EXPERIMENT`, (3) lazy `from academic_pipeline.config import DEFAULT_CONFIG`, (4) `configure_logging` with rotation params from DEFAULT_CONFIG, (5) `atexit.register(shutdown_observability)` for graceful shutdown, (6) `configure_observability()` then conditionally `init_dbos()` if `--durable`. Loop must keep this exact order — `configure_ssl` BEFORE `configure_observability` because Logfire HTTP needs SSL trust store loaded.

**`_cli_state: dict[str, bool] = {"dbos": False}`** (line 82): the ONLY mutable module-level state in cli.py. Stores DBOS init result so `_make_pipeline` can pass `use_dbos=` correctly. Loop must NOT add other module state — use closure or thread parameters through.

**`_parse_authors`** format: pipe-separated `"Name | Affiliation | email"`. Email is optional (skipped if empty). Loop adding new author fields must extend the parser AND update CLAUDE.md examples in lockstep.

**`_make_pipeline` lazy-imports** sdk.Pipeline + Author + PaperConfig — keeps `--help` startup fast (no heavy import chain). Loop adding new top-level imports to cli.py must keep them inside command handlers or `--help` time regresses.

**CRITICAL drift between CLAUDE.md and cli.py** (verified ralph-75): `CLAUDE.md` lines 64-68 document individual phase commands `python -m academic_pipeline research "topic"`, `write "topic"`, `review`. **THESE COMMANDS DO NOT EXIST** in cli.py — only the 7 commands above are registered. Either add the phase commands (matches docs, allows phase-by-phase debugging) OR remove the section from CLAUDE.md. Decision needed for v2.5.0.

**`cleanup-state` command (PRD §6.9.T5) is also UNIMPLEMENTED** — referenced in §6.9.T5 task but no `@app.command(name="cleanup-state")` decorator exists. Phase 2 wiring required before T5 can ship.

### 13.7 When in doubt, defer to the docs

Before adding a new agent/capability/hook pattern, check:
1. https://ai.pydantic.dev/agent-spec/ — YAML/JSON spec format
2. https://ai.pydantic.dev/capabilities/ — built-in capabilities + custom registration
3. https://ai.pydantic.dev/api/agent/ — agent class API surface
4. https://ai.pydantic.dev/api/settings/ — `ModelSettings` and provider-specific subclasses (`AnthropicModelSettings`)
5. https://ai.pydantic.dev/api/messages/ — `ModelMessagesTypeAdapter` for persistence
6. https://ai.pydantic.dev/thinking/ — adaptive vs extended thinking
7. https://platform.claude.com/docs/en/build-with-claude/effort — Anthropic effort levels

Never invent an API based on intuition. If a pattern looks plausible but you can't find it in the docs above, it probably doesn't exist.

---

## 14. Document Change Log

| Date | Change | Iteration |
|---|---|---|
| 2026-05-05 | Initial PRD (12 components, 1017 lines) | 0 |
| 2026-05-05 | Closed 10 gaps from gap audit; added §6.13 Observability + §6.14 CI/Release (14 components, 1140 lines) | gap-audit |
| 2026-05-05 | Added §6.15 Output Verification + LLM-as-Judge with chapter 3 + chapter 5 methodology (15 components, 1289 lines) | gap-audit-2 |
| 2026-05-05 | Removed §6.15.T8 A/B comparator as overkill; folded version comparison into spot-review eyeball (1282 lines) | simplification |
| 2026-05-06 | Iteration 1: web-verified PydanticAI / Anthropic / Dagster / judgy claims; added §13 PydanticAI Conventions appendix; switched §6.15.T7 from port to `judgy` PyPI install | ralph-1 |
| 2026-05-06 | Iteration 2: added §15 Files Inventory — per-component verified file paths so the loop can't miss a file when executing a delta | ralph-2 |
| 2026-05-06 | Iteration 3: added §16 Cross-Component Data Handoff Map — 15 Phase 2 artifacts, verified class names against `models/`, producer/consumer/state-field per artifact, naming-correction table (Thesis → ThesisStatement, etc.) | ralph-3 |
| 2026-05-06 | Iteration 4: added §17 Error-Code Namespaces — 18 namespaces (TRC verified existing, 17 new), 7 allocation rules, loop directive forbidding ad-hoc error strings | ralph-4 |
| 2026-05-06 | Iteration 5: added §18 events.jsonl Schema — universal envelope, 7 existing event-type schemas (verified via real samples in `output/`), 7 new v2.5.0 event types with full JSON shape, forward-compat rules, append-only invariant | ralph-5 |
| 2026-05-06 | Iteration 6: added §19 Regression Vectors — 34 R-rows covering every Phase 2 wiring with 🔴/🟡/🟢 severity, blast radius, mitigation; loop directive forbidding merge of unmitigated 🔴 regressions | ralph-6 |
| 2026-05-06 | Iteration 7: added §20 Migration Scripts Inventory — 7 scripts with read/write/idempotency contracts, 9-step migration runbook for v2.4.0→v2.5.0, archive-not-delete safety pattern | ralph-7 |
| 2026-05-06 | Iteration 8: added §21 Failure Mode Traceability Matrix — 6 failure modes mapped to preventer wirings, detector judges, hard-gate error codes, root-cause anti-patterns; bidirectional check + surface→action mapping | ralph-8 |
| 2026-05-06 | Iteration 9: added §22 Test Cadence + Tier Mapping — 4 tiers (small/medium/large/regression), per-component test count targets summing to ~860 net delta, CI job matrix, fixture inventory | ralph-9 |
| 2026-05-06 | Iteration 10: added §23 Definition of Done — single-page tag-day checklist; fixed 3 gate-numbering drift bugs (§5.5 12→15 components, §6.15 contract gates 9-13→9-12, §11 tag-flow gates 9-13→9-12); pre-tag pre-flight bash script | ralph-10 |
| 2026-05-06 | Iteration 11: added §24 Example Agent YAML Stubs — verified against existing `chain_of_ideas_extractor.yaml` + `senior_gatekeeper_reviewer.yaml`; canonical LLM-as-Judge template + full hedge_language judge instantiation + construction notes for the other 5 judges; loop directive forbidding from-scratch YAML writes | ralph-11 |
| 2026-05-06 | Iteration 12: added §25 Logfire Span Schema — universal span attributes, PydanticAI inherited spans + 5 custom span types matching §18 events.jsonl; naming conventions, recommended saved searches, loop directive enforcing events.jsonl ↔ Logfire span parity | ralph-12 |
| 2026-05-06 | Iteration 13: added §26 Decision Log — 30 D-rows capturing why X over Y for every major architectural choice (Dagster, AutoGluon, judgy, PromptedOutput, adaptive thinking, etc.) + 6 open questions; loop directive forbidding silent reversals | ralph-13 |
| 2026-05-06 | Iteration 14: added §27 Token Budget — verified Opus 4.7 pricing ($5/$25 per M, cache reads $0.50, batch 50% off), per-agent-type cost ($0.08 judge → $1.50 verifier), per-run breakdown ~$40, regression suite ~$355, total v2.5.0 ship cost ~$1200, rate-limit headroom check | ralph-14 |
| 2026-05-06 | Iteration 15: added §28 Anti-Pattern Catalog — 45 AP-rows consolidated from §13.2/§15/§17/§19/§22.6/§24.4/§25.5/§26 plus 4 new global APs (force-push, --no-verify, scope into non-goals, Spec 9 opportunism); single searchable list for pre-merge grep | ralph-15 |
| 2026-05-06 | Iteration 16: added §29 Open Questions Tracker — 20 OQ-rows with default-if-unanswered + resolution trigger + owning component; converts implicit assumptions into explicit asks; loop directive: use documented default + TODO comment, never silently bypass | ralph-16 |
| 2026-05-06 | Iteration 17: consistency sweep — caught + fixed `checklist_ethics_enabled` → `ethics_checklist_enabled` (4 places, verified against `docs/superpowers/specs/2026-05-03-checklist-ethics-design.md:148`); marked OQ5 RESOLVED in §29 with first row in resolution log. This iteration validates the OQ-tracker pattern works | ralph-17 |
| 2026-05-06 | Iteration 18: state-field verification pass — caught 3 more drift bugs by reading actual `<subgraph>/state.py` files: `ResearchState.development_chain` → `.chain`, `.thesis_statement` → `.thesis`, `ReviewState.pointwise_novelty_report` → `.novelty_report`, class `PointWiseNoveltyReport` does not exist (use `NoveltyReport`). §16 rows 1, 2, 5 fixed; naming-correction table extended; 2 new OQ resolution rows. | ralph-18 |
| 2026-05-06 | Iteration 19: continued state-field verification on remaining state.py files — caught 3 more bugs: `ExperimentState.scored_designs` does not exist (actual: `selected_designs` + `design_comparison`); `IntegrityState.ethics_checklist` does NOT exist at HEAD (Phase 2 must add); trace tokens live at `WritingState.numerical_store: NumericalStore` not just a JSON file. §16 rows 8, 9, 11 fixed; 3 more RESOLVED OQ rows. | ralph-19 |
| 2026-05-06 | Iteration 20: agent-registry pattern verification — found 3 PydanticAI patterns missing from §13.1 (used in actual codebase but PRD didn't document): `pydantic_ai_skills.SkillsCapability`, `AnthropicCompaction(token_threshold=...)`, `throttle_hooks` as a Hooks-instance capability. Added 3 rows to §13.1 with verified import paths + line numbers. | ralph-20 |
| 2026-05-06 | Iteration 21: PipelineState verification — confirmed §16 row 3 (novelty_gate_result) correct; found `copilot_comments` field missing from §16 (added as row 16); discovered dual-layer state pattern (subgraph state + PipelineState mirror after handoff) not documented; added "Dual-layer state caveat" subsection to §16 with 8 verified mirror fields. 2 more RESOLVED OQ rows. | ralph-21 |
| 2026-05-06 | Iteration 22: Makefile + conftest verification — found `make test-medium` Makefile target does NOT exist (CI job by that name invokes `make test-integration`); §22.3 row clarified. Added 3 missing TestModel helpers to §13.1 (`make_structured_test_model`, `make_union_test_model`, `make_field_overrides_test_model`) — loop must pick the right one per agent's output_type. 2 more RESOLVED OQ rows. | ralph-22 |
| 2026-05-06 | Iteration 23: **first clean verification pass.** Verified all 19 config.py defaults against PRD claims (tau_warn=0.78, tau_block=0.92, n_design_alternatives=4, k_designs_to_run=2, max_dialogue_turns=3, max_node_iterations=2, node_quality_threshold=7.0, max_integrity_fix_loops=3, experiment_seeds=[42,123,456], experiment_timeout=1800, compaction_token_threshold=800_000, llm_timeout=600, llm_max_retries=3, http_timeout=20, http_max_retries=3, pointwise_novelty_top_n_per_claim=5, target_journal, target_acceptance_rate=0.20, cascade_short_circuit on Stage A/B = true / Stage C = false). All match. Zero drift bugs found. | ralph-23 |
| 2026-05-06 | Iteration 24: pyproject.toml dep verification — found 4 issues: (1) `defusedxml` declared but ZERO src/ usages (§6.12.T7 extended); (2) Makefile uses `npx basedpyright`, pyproject pins `pyright>=1.1`, CI uses `uv run pyright` — three sources two tools (new §6.14.T7); (3) `pip-audit` + `bandit` declared but never run in CI (new §6.14.T8); (4) mkdocs deps declared but no `mkdocs.yml` — needs decision (new §6.14.T9). 4 more RESOLVED OQ rows. | ralph-24 |
| 2026-05-06 | Iteration 25: agent-registry-key verification — read all 5 subgraphs' `agents.py`. Verified 50 total keys (research 12, review 12, writing 13, experiment 11, integrity 2). All match PRD. One clarification needed: writing's `"visualization"` key was role-renamed to "figure curator" but the registry key + file + `name:` field unchanged — added inline note to §6.3 current state. | ralph-25 |
| 2026-05-06 | Iteration 26: pipeline/nodes.py + experiment/graph.py node verification — caught **5 node-name drift bugs**: (1) §5.1 referenced non-existent `ExperimentFixNode` (no separate fix node — retry is inline); (2) `ExperimentDesignerNode` → actual `ExperimentDesignNode` (no -er-); (3) `ExperimentDesignerBundleNode` → actual `ExperimentDesignBundleNode`; (4) `ImprovementNode` doesn't exist (inline + agent yaml only); (5) `MultiSeedNode` doesn't exist (inline). §6.2 node count corrected from 7 → 9. Important asymmetry documented: agent registry KEYS use -er-, node CLASSES don't. | ralph-26 |
| 2026-05-06 | Iteration 27: real-production-events verification — sampled `output/run-*/events.jsonl` files. Found 3 actual event types not documented in §18.2: `watchdog_killing` (with pgid/age_s/strike fields), `watchdog_killed` (with killed_cleanly), `watchdog_resuming`. All 3 added with verified field shapes. Caveat added to §6.6.T2: new generic `recovery_event` should COEXIST with these 3 specific types (option a) — backward-compat for Logfire saved searches and scripts. | ralph-27 |
| 2026-05-06 | Iteration 28: dashboard whitelist verification — read `runtime/dashboard.py:213-216` apply_event handlers. Found 2 MORE watchdog types beyond the 3 from ralph-27: `watchdog_resumed` (success) + `watchdog_aborted` (3-strikes). Complete watchdog set = 5 types. Plus verified `pipeline_status` enum (5 values). Both added to §18.2. | ralph-28 |
| 2026-05-06 | Iteration 29: enum verification against `core/enums.py` + real production events.jsonl. Caught **4 enum drift bugs**: (1) Stage value is `"write"` not `"writing"` (subgraph folder is `writing/`, AgentType value is `"writing"`, but Stage.WRITE.value is `"write"` — three different strings for the same concept); (2) `Verdict.PASS_WITH_NOTES` doesn't exist — actual is `Verdict.PASS_WITH_CONDITIONS`; (3) `EditorialDecision` values are Title Case with spaces (`"Accept"`, `"Minor Revision"` etc.) not lowercase; (4) `PipelineStatus` (6 values, enum) and dashboard `pipeline_status` (5 string-literals) are two DIFFERENT concepts often conflated. Added §18.6 enum reference table + 2 disambiguation subsections. | ralph-29 |
| 2026-05-06 | Iteration 30: citations.py verification — clean pass. Confirmed `tools/bibliography/citations.py::STYLE_DISPATCH` (line 152) covers exactly 5 styles with literal strings `"APA7"` `"Chicago"` `"MLA"` `"IEEE"` `"Vancouver"`. ACL anthology absent — confirms §6.7.T9 task is needed. §6.7.T9 description tightened with exact API path + literal strings. | ralph-30 |
| 2026-05-06 | Iteration 31: Spec 6 design doc verification — caught **3 cascade drift bugs**: (1) cascade has 4 stages (NUMERICAL_GROUNDING / NOVELTY / METHODOLOGY / **NARRATIVE**), PRD §6.4 mentioned only A/B/C — fixed §16 row 6; (2) `StageVerdict` enum has 4 values (`pass`/`short_circuit_reject`/`skipped`/`not_run`), not pass/fail — fixed §18.2 cascade_verdict span schema; (3) §17 CAS namespace gained CAS006 StageDNarrativeWeak. Documented Stage D doesn't short-circuit (leaf). | ralph-31 |
| 2026-05-06 | Iteration 32: Spec 4 design doc + traceability/_patterns.py verification — **caught the trace token notation bug.** PRD used `{{trace:expr_id}}` in 4 places. Actual notation is `⟨num:label⟩` (Unicode angle brackets U+27E8/U+27E9, `num:` prefix, Python identifier label) per regex `r"⟨num:(?P<label>[a-zA-Z_][a-zA-Z0-9_]*)⟩"`. Fixed all 4 occurrences. Plus expanded §16 row 5: NoveltyReport overall verdict is `REJECT_NOVELTY` if any claim is `redundant`; `partial_overlap` is a warning, not a rejection (Spec 4 Non-goal #3). | ralph-32 |
| 2026-05-06 | Iteration 33: Spec 1 design doc verification — caught **2 substantive design details PRD missed**: (1) hedges vs aborting phrases are TWO different categories (hedges retry via ModelRetry/TRC001; aborts fail-loud/TRC002, no retry) with specific phrase lists per category. Hedge proximity is **5 tokens BEFORE** the `⟨num:label⟩` (directional!), config via `HEDGE_PROXIMITY_TOKENS=5`. §6.11.T2 expanded with both lists. (2) LaTeX target naming convention: `\hyperlink{num_<label>}{<value>}`, `\hypertarget{num_<label>}{}`, `\hypertarget{code_<run>_<line>}{}`. §16 row 9 expanded with full 9-field `NumericalProduct` schema + naming convention. | ralph-33 |
| 2026-05-06 | Iteration 34: Spec 5 design doc verification — caught **1 spec-doc internal inconsistency + full PersonaSpec axis enumeration**. Spec doc says persona reviewers replace `peer_reviewer`, but `peer_reviewer` lives in `writing/agents.py` not `review/agents.py`. Actual replacement: senior_gatekeeper→perspective_reviewer, applied_practitioner→domain_reviewer, methodology_purist→methodology_reviewer. Plus full 24-combination axis enumeration (Commitment×2, Intention×4, Knowledgeability×3). §6.4.T2 + §16 row 4 expanded. | ralph-34 |
| 2026-05-06 | Iteration 35: Spec 8 design doc verification — caught **3 details PRD missed**: (1) the 12 standard EthicsChecklist item names verbatim (e.g., `human_subjects_disclosed`, `irb_approval_documented`, ..., `potential_misuse_acknowledged`) — not just "12 items" abstractly; (2) `overall_verdict` enum has 3 values `pass` / `pass_with_waivers` / `block`; (3) NEW file `integrity/specs/ethics_reviewer.yaml` (note `-er` suffix) needed but missing from §15 §6.5 Create column. Source-verification artifacts must inject into agent context for structural COI detection. §16 row 8 + §6.5.T1/T2 + §15 expanded. | ralph-35 |
| 2026-05-06 | Iteration 36: Spec 3 design doc verification — caught **NoveltyVerdict enum drift** (PRD §18.2 said `"soft_warn"`, actual is `"partial"` per `novelty_gate.py:130`). Plus surfaced design ambiguity in §6.1.T5: Spec 3 says generate differentiation_paragraph on PARTIAL verdict; PRD said RQ-refinement iteration. Two different mechanisms — added as OQ-NEW-35 (partial; Jackson must decide). §6.1.T5 + §16 row 3 + §18.2 expanded. | ralph-36 |
| 2026-05-06 | Iteration 37: Spec 2 design doc verification — caught **node-count drift + 2 enum gaps + 1 architectural trap**: (1) ONE `ChainOfIdeasNode` calling TWO agents, NOT two separate nodes — PRD §6.1.T2 + §16 rows 1-2 corrected; (2) `MilestoneType` 5 values + `EdgeRelation` 4 values + `DevelopmentChain.terminal_unsolved_problem` field — added to §16 row 1; (3) `ThesisStatement.novelty_dimension` 4-value Literal — added to §16 row 2; (4) **TWO different "novelty dimension" enums in codebase** — `ThesisStatement.novelty_dimension` (Spec 2, 4 values) vs `ClaimNoveltyDimension` (Spec 4, 5 values). Loop must not conflate. | ralph-37 |
| 2026-05-06 | Iteration 38: Spec 7 design doc verification — final SCI spec verified. Caught **3 details**: (1) 4 Pydantic models not 3 — `DesignScore` was missing from §16, carries the 5-criterion scoring rubric; (2) `DesignComparison.discussion_paragraph` auto-inserted into paper's Discussion section — important hand-off; (3) Spec 7 says rename ExperimentDesignNode → ExperimentDesignBundleNode but actual codebase has both coexisting. §16 row 11 + §6.2.T6 expanded. **All 8 SCI specs now verified.** | ralph-38 |
| 2026-05-06 | Iteration 39: integrity model deep verification — caught **3 substantial gaps**: (1) `MaterialPassport` (7 fields + 2 properties + skip-optimization logic) was completely undocumented in PRD despite being used in `PipelineState.material_passport` — added as §16 row 17; (2) integrity subgraph has 5-phase architecture (PhaseA References / PhaseB CitationContext / PhaseC Data / PhaseD Originality / PhaseE Claims) with 18+ classes in `models/integrity.py`, NOT "1 composite node" as PRD said — §6.5 current state corrected; (3) `VerificationStatus` Literal (`VERIFIED`/`UNVERIFIED`/`STALE`) + `PASSPORT_FRESHNESS_HOURS=24` constant documented. | ralph-39 |
| 2026-05-06 | Iteration 40: `tools/integrity_tools.py` verification — caught **2 details**: (1) 3 distinct async functions, NOT 3 conflated capabilities (`extract_claims`, `check_plagiarism_heuristic`, `detect_ai_style_indicators`). All return JSON strings (legacy pattern, pre-dates `models/integrity.py`). Claim IDs are `CLAIM-NNN` zero-padded; plagiarism verdict literal is `"REVIEW_NEEDED"\|"NO_FLAGS"`; AI-style is separate not nested. §6.5 current state expanded. (2) §6.5.T4 made concrete: refactor target is `detect_ai_style_indicators(text)→str` → `(sections)→dict[section, AIStyleScore]` with new Pydantic model + `legacy_ai_style_detection` escape hatch. | ralph-40 |
| 2026-05-06 | Iteration 41: `runtime/throttle.py` verification — caught **2 details + 1 stale-doc bug**: (1) `throttle_hooks` is a module-level singleton with shared counter across ALL agents in process; `make_throttle_hooks()` factory exists for tests; 3 hook handlers (before_model_request / run_error / model_request_error). (2) Throttle skips first call, applies 10s delay starting call #2. (3) **Stale docstring** at `throttle.py:1` says "Vertex AI quota protection" but codebase uses Anthropic — surfaced as OQ-NEW-48 partial (fix-in-future-iteration; behavior correct, comment misleading). §13.1 row expanded. | ralph-41 |
| 2026-05-06 | Iteration 42: `recovery/supervisor.py` verification — caught **1 architectural pattern + 2 constants**: (1) **recursive-supervisor pattern** — a single user-visible run can span multiple supervisor processes across recovery (original supervisor exits on SIGKILL → watchdog spawns fresh supervisor + fresh watchdog). Critical for log-aggregation: never assume one supervisor process per run. PRD §6.6 didn't capture. (2) Constants `_THREAD_ID_TIMEOUT_S=60` + `_WATCHDOG_GRACEFUL_S=10` documented. (3) `_strip_flag(args, *flags)` helper for typer "last wins" workaround. | ralph-42 |
| 2026-05-06 | Iteration 43: `tools/execution/sanity.py` verification — enumerated **6 specific sanity checks** in `sanity_check_results` with hardcoded thresholds (NaN/Inf/negative-bounded/high-accuracy>0.99/all-identical/no-metrics). Bounded-metric set has 7 names; loop must extend if breadth-mode adds new bounded metrics. Returns `list[str]` not Pydantic — refactor candidate (OQ-NEW-52 partial, v2.6.0+). Documented all 5 functions (sanity_check_results / verify_plan_alignment / _check_url_reachable / verify_dataset_urls / send_dataset_alert). §6.2 current state expanded. **Initially put in §6.5 wrong** — relocated mid-iteration. | ralph-43 |
| 2026-05-06 | Iteration 44: `runtime/evaluator.py` verification — caught **4 substantial behavioral details PRD missed**: (1) median aggregation for ≥3 evaluators, MIN for exactly 2 (conservative pessimism on small panels); (2) PASS requires BOTH every-dim-≥-threshold AND average-≥-threshold; (3) rubber-stamp anti-sycophancy warning when any single evaluator gives all scores ≥9.5; (4) verdict literal is `"PASS"\|"NEEDS_IMPROVEMENT"` (yet ANOTHER verdict concept distinct from `Verdict` enum's 6 values). §6.11 current state expanded. 4 more RESOLVED OQ rows. | ralph-44 |
| 2026-05-06 | Iteration 45: `sdk/pipeline.py` verification — caught **2 catches**: (1) **persistence class drift** — PRD referenced `FileStatePersistence` in 4 places, actual is `SqliteStatePersistence` (no FileStatePersistence class exists); fixed all 4 via replace_all. (2) Documented `Pipeline()` constructor signature (7 params), auto-thread-id format `run-MMDD-HHMM_xxxx`, DBOS opt-in via `use_dbos=True`, and confirmed `Pipeline.observe(callback)` does NOT exist at HEAD (§6.12.T2 net-new work). §6.12 current state expanded. | ralph-45 |
| 2026-05-06 | Iteration 46: `experiment/harness.py` verification — caught **substantial 5-layer architecture + open architectural question**: (1) 5 enforcement layers documented (PrepareTools / before_tool ML-block / after_tool template-mark / after_tool result-sensor / output_validator); (2) 14 FORBIDDEN_IMPORTS + 4 ALLOWED_SKLEARN + 5 ALLOWED_AUTOGLUON + 3 TEMPLATE_MAP enumerated; (3) **Open question**: §6.2.T7 deletes InteractiveMLNode — what about harness.py? 3 options surfaced as OQ-NEW-59 partial (recommend option a: delete; ConfigWriter has no executable surface to constrain). §6.2.T7 expanded with both possibilities. | ralph-46 |
| 2026-05-06 | Iteration 47: `models/writing.py` + `models/shared.py` verification — caught **4 substantial gaps + 1 architectural collision**: (1) `IssueSeverity` collision (4-value enum lowercase vs 3-value Literal uppercase, same name) — new §18.6.1 trap subsection; (2) **5th verdict-like type discovered**: `IntegrityVerdict` Literal (3 values); (3) `StructureType` has 6 values, not "IMRaD vs sysrev" binary — important for §6.15 fixture diversity; (4) 13 Literal types in `models/shared.py` enumerated. Verdict-concept count now 5. §18.6 enum table substantially extended. | ralph-47 |
| 2026-05-06 | Iteration 48: `models/research.py` (28 classes) verification — caught **3 schema details + 2 deletion-task expansions**: (1) `FINERScores` uses 3-5 range NOT 0-10, 5 dimensions + average property; (2) `RQBrief.sub_questions` Pydantic-constrained to 2-5; methodology_type Literal of 3 values; (3) **§6.1.T6 expanded** to delete `EthicsReviewOutput` class (orphan after agent removal); **§6.1.T7 expanded** to delete 3 KnowledgeGraph-specific orphan classes (`KnowledgeGraph`, `SourceRelationship`, `ResearchCluster`). Without these expansions, dead code would survive Phase 2. | ralph-48 |
| 2026-05-06 | Iteration 49: `models/review.py` (22 classes) verification — final large model file. Caught **2 details + 1 refactor opportunity**: (1) `PeerReviewReport` schema: `confidence_score 1-5` (not 0-10), `strengths/weaknesses 1-5 items`, `summary 150-250 words`; (2) class duality during legacy transition: `PeerReviewReport` (legacy trio) + `PersonaReviewOutput` (Spec 5) both stay; (3) `overall_recommendation: str` untyped — refactor to `EditorialDecision` enum recorded as OQ-NEW-69 partial for v2.6.0+. **All 5 large model files verified** (research / review / writing / cascade / chain / etc.); no orphan-class candidates in review.py. | ralph-49 |
| 2026-05-06 | Iteration 50 (round milestone): `tools/agent_cache.py` verification — caught **2 details + 1 task de-scope**: (1) `AgentMessageCache(cache_dir, agent_name)` API verified — 4 methods, corrupt cache silently returns None (doesn't raise); (2) §6.9 current state expanded with verified API surface; (3) **§6.9.T2 reconsidered** — proposed `for_agent` factory is sugar over existing constructor. Recommendation: classmethod sugar instead of full refactor. Task description updated; full refactor de-scoped. | ralph-50 |
| 2026-05-06 | Iteration 51: `recovery/heartbeat.py` + `recovery/process_state.py` verification — caught **2 fine details**: (1) Heartbeat default 30s, daemon thread (not asyncio — explicit reason: blocked event loop), atomic .tmp+rename, Prefect #21184 precedent cited; (2) ProcessLock writes 2 files (`.pid` + `.pgid`) with graceful fallback when `os.getpgid(0)` fails (writes own PID as PGID; watchdog degrades to `os.kill`). §6.6 layer-by-layer expansion. | ralph-51 |
| 2026-05-06 | Iteration 52: `recovery/transport.py` (L1) + `recovery/bounded_run.py` (L2) verification — caught **1 critical scope clarification + 1 detection-time math + 1 design rationale**: (1) **L2 does NOT catch stuck-in-recv stalls** — PRD prose was misleading; `asyncio.wait_for` cannot preempt sync syscalls in kernel. L2 only catches LEGITIMATE-slow LLM thinking. Stuck-in-recv = L1 (keepalive) + L4 (watchdog). (2) L1 detection time math: 60s idle + 4×15s probes = 120s. (3) macOS default keepidle = 2 hours without keepalive socket options; Prefect / mcp-stdio precedents cited. §6.6 L1+L2 descriptions substantially corrected. | ralph-52 |
| 2026-05-06 | Iteration 53: `recovery/watchdog.py` (L4) verification — caught **2 MAJOR DRIFTS**: (1) **`max_idle_s=600s default, NOT 75s** as PRD said in 4 places — 75s caused false-positive kills (run-0504-1802_ec44); legitimate nodes spend 60-120s between events.jsonl writes. Fixed all 4 places. (2) **heartbeat.txt is NOT used for stall detection** — daemon-thread heartbeat keeps ticking even when main hung in await; trusting it masked the run-0504-1212_cf0d 1h41m wedge. Only events.jsonl is the proof-of-progress signal. §6.6 L4 description rewritten with explicit "loop must NOT add heartbeat to stall logic" warning. Plus 4 watchdog constants verified (poll_interval=30, graceful=10, resume_timeout=60, max_strikes=3). | ralph-53 |
| 2026-05-06 | Iteration 54: `traceability/copilot.py` + `dialogue.py` verification — caught **3 details**: (1) `run_writer_reviewer_dialogue` is FULLY IMPLEMENTED — §6.10.T1 just needs to call it from a new SectionDialogueNode (not write the helper); (2) **`DEFAULT_TERMINATION_PHRASE = "The section does not require any changes"`** exact verbatim string; (3) **Quantified benefit per data-to-paper**: 2-3 single-sentence copilot comments turn 90% error rate → 10-20%. §6.10.T1 + §16 row 16 expanded with verified signatures + termination phrase + benefit numbers. | ralph-54 |
| 2026-05-06 | Iteration 55: `traceability/code_appendix.py` + `notes_appendix.py` + `substitution.py` verification — caught **4 details + 1 silent-bug refactor opportunity**: (1) substitute_tokens supports HTML mode (plain value) in addition to LaTeX (\hyperlink); (2) both appendix generators return empty string when no inputs — caller MUST NOT include section if empty; (3) code_appendix uses _CodeRun Protocol for structural typing — works with StubCodeRun (tests) OR ExperimentRun (prod); (4) notes_appendix **silently skips labels not in store** — refactor opportunity (OQ-NEW-84 partial, v2.6.0+). §16 rows 9, 13, 14 substantially expanded. | ralph-55 |
| 2026-05-06 | Iteration 56: `traceability/validators.py` verification — caught **4 substantial findings**: (1) ABORTING_PHRASES has **9 entries** (not 4 as PRD §6.11.T2 said): adds `[to be`, `pending full search`, and 3 angle-bracket variants `<insert`/`<unknown`/`<missing`; (2) Discrepancy between `validators.py` raising `UnexpectedModelBehavior` and `errors.py` defining `NumericValidatorAbort/TRC002` — same case, different paths (OQ-NEW-86 partial, reconcile in v2.6.0); (3) Numeric pattern requires preceding context char `[$,{<=\s\n\(\[]` (sophisticated false-positive prevention for dates, etc.); (4) Label-not-in-store error shows up to 10 available labels — "tell the model what's available" pattern. §6.11.T2 substantially corrected. | ralph-56 |
| 2026-05-06 | Iteration 57: `traceability/context_spec.py` (25 lines) verification — caught **3 task-description corrections**: (1) PRD §6.10.T2 said "move from global definitions in context_spec.py" but NO global instances exist there (file only defines the class). Actual work: define per-agent INSTANCES in each agent's home module; (2) `Literal["all"]` sentinel ≠ `[]` (no labels allowed) — loop must use right one per agent; (3) `build_curated_context` raises TypeError on non-ContextSpec input (no duck typing). §6.10.T2 + §6.10.T3 + §16 row 10 corrected. | ralph-57 |
| 2026-05-06 | Iteration 58: `runtime/citation_resolver.py` verification — caught **3 details**: (1) **3 resolver functions** for 3 render paths (LaTeX natbib `\cite{}`, numbered `[1,2]`, pandoc `[@bibkey]`); loop must pick right one per template; (2) Pandoc multi-key uses **semicolon** separator (`[@a; @b]` not `[@a,@b]`); (3) Adjacency merging requires BOTH keys known; unknown brackets (NCT/CVE/equation labels) pass UNCHANGED. §6.7 current state substantially expanded. | ralph-58 |
| 2026-05-06 | Iteration 59: `runtime/paper_renderer.py` (21.5K — biggest single file) verification — caught **3 substantial findings**: (1) 2 public renderers (markdown + latex); production uses `--natbib` + **`acl_natbib.bst`** style file PRD §6.7 didn't mention; (2) `[FIGURE: N]` marker contract — missing markers LEFT IN PLACE (visible gap), NOT silent-skipped (anti-pattern); (3) Renderer conventions: abstract is YAML frontmatter not section, ref_map 1-indexed, multi-author `"; "` separator. §6.7 current state substantially expanded. | ralph-59 |
| 2026-05-06 | Iteration 60 (round milestone): `tools/rendering/latex_compiler.py` verification — caught **CRITICAL ANTI-PATTERN + 2 design rationales**: (1) `--biblatex` and `-V biblio-style` MUST NOT be added — acl.sty calls `\bibliographystyle{acl_natbib}` internally at acl.sty:195; double `\bibstyle` crashes bibtex with "Illegal, another \bibstyle command". Loop adding what looks like a missing flag would silently break every ACL build. (2) `--natbib` flags are CONDITIONAL on bib_source truthiness. (3) Per-build asset copy because pandoc resolves filter/header paths relative to cwd. Exact pandoc command documented. | ralph-60 |
| 2026-05-06 | Iteration 61: `runtime/dashboard.py` (12.5K) full surface verification — caught **3 details + 1 architectural trap upgrade**: (1) 4 frozen dataclasses (NodeInfo, StageInfo, WatchdogAction, RunState) + 5 pure functions form the renderer; `read_events` design philosophy: never raises, returns empty list on missing; (2) **THIRD status concept discovered**: `StageInfo.status` (4 values) — joins PipelineStatus enum (6) and RunState.pipeline_status (5). §18.6 trap upgraded from "two status concepts" to "three". (3) `WatchdogAction.action` Literal verified verbatim (5 values matching §18.2 watchdog event types). | ralph-61 |
| 2026-05-06 | Iteration 62: `experiment/dagster_runner.py` (1.6K) verification — caught **3 details**: (1) 2-step subprocess chain — `uv sync` hardcoded 600s timeout + `dagster job execute` configurable 1800s default; (2) **template-to-workspace copy invariant** — template's `pipeline/` becomes workspace's `src/pipeline/` (per `-m pipeline.definitions` resolution); §6.2.T1 template-copy step must preserve; (3) `succeeded` requires BOTH returncode 0 AND results.json exists. §6.2 current state expanded. **NOTE: claim (2) was WRONG — see ralph-63 correction.** | ralph-62 |
| 2026-05-06 | Iteration 63: `experiment/template_copier.py` (54 lines) verification — caught **MAJOR PATH CORRECTION + 2 frozenset details**: (1) Earlier ralph-19/26/62 wrongly claimed template path was `templates/dagster-experiment/pipeline/definitions.py`. ACTUAL is `templates/dagster-experiment/src/pipeline/definitions.py` — verified via `ls templates/dagster-experiment/` showing `src/` at top level. Template_copier preserves structure (no transformation). Fixed all 7 PRD occurrences via replace_all + corrected ralph-62 claim. (2) `_EXCLUDE_DIRS` 8 entries + `_EXCLUDE_FILES` 2 entries verified verbatim. (3) `_find_repo_root` walks up looking for template dir — fails loud if missing. **Self-correcting iteration**: caught my own earlier drift. | ralph-63 |
| 2026-05-06 | Iteration 64: actual template `src/pipeline/` contents verification — caught **MAJOR ARCHITECTURE CORRECTION**: NO `strategies/` directory exists. Actual structure: `assets/_common/` (fixed) + `assets/experiment/` (auto-discovered per-run @asset modules generated by config_writer agent). §6.2.T1-T4 reframed from "add strategy modules" to "extend config_writer + add canonical examples". §15 §6.2 row Create column corrected. Workspace contract documented per definitions.py docstring. **Second self-correction in 2 iterations** — proves verification methodology robust against my own earlier drift. | ralph-64 |
| 2026-05-06 | Iteration 65: `config_models.py` schema verification — caught **MAJOR DESIGN-PHILOSOPHY CORRECTION**: schema is ORCHESTRATION-ONLY (4 top-level fields), algorithm-specific config DELIBERATELY excluded. §6.2.T2/T3 said "add timeseries.partitioning + multimodal.modality_columns to config_models.py" — both WRONG, violate the design philosophy. Reframed: algorithm config goes inside agent-generated @asset modules. Plus DatasetConfig schema verified (4 fields, `entity_id_column` must NEVER be a feature). **Third self-correction in 3 iterations** — verification methodology continues to find my own earlier drift. | ralph-65 |
| 2026-05-06 | Iteration 66: `resources.py` verification — caught **4 critical patterns**: (1) workspace cwd convention (Dagster launched with cwd=workspace/); (2) `yaml.safe_load` security-critical (NOT yaml.load); (3) DuckDB single-store invariant — `workspace/experiment.duckdb` is single store for ALL materializations; (4) MLflow nested-run pattern — `mlflow.start_run(nested=True)` required in agent-generated @asset code. §6.2 current state expanded with full resource API + 3 fixed workspace path inventory. | ralph-66 |
| 2026-05-06 | Iteration 67: `assets/_common/data_load.py` (73 lines) verification — caught **CRITICAL DAGSTER ANTI-PATTERN + 3 details**: (1) `from __future__ import annotations` MUST BE OMITTED in @asset modules (Dagster does runtime identity checks on annotations; PEP 563 breaks it). Added as §28 AP46. Plus AP47 (CSV options), AP48 (yaml.safe_load), AP49 (single duckdb), AP50 (nested=True), AP51 (no algo config in config_models.py) — codifying the design invariants from iters 65-67. (2) raw_data @asset signature + table-naming convention (`raw_<stem>` with dashes→underscores). (3) 3 source schemes + 2 file extensions only. §6.2 + §28 substantially expanded. | ralph-67 |

---

## 15. Files Inventory

Per-component file inventory. **Verified against actual codebase tree at commit `832c71e` (2026-05-06).** Modify column = files that exist today and will change. Create column = files that do not exist today and need to be made. Delete column = files to remove (after their replacement is verified working). Paths are relative to repo root.

When the loop picks up a delta task, it MUST cross-check the files-it-modifies against the relevant row here. If the loop's plan touches a file not listed, either the plan is wrong or this inventory is incomplete — investigate before merging.

### §6.1 Research subgraph
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/research/graph.py`, `research/agents.py`, `research/state.py`, `research/novelty_gate.py`, `research/specs/synthesis.yaml`, `research/specs/research_question.yaml`, `models/research.py`, `config.py`, `configs/default.yaml` |
| **Create** | `tests/unit/research/test_chain_of_ideas_phase2.py` |
| **Delete** | `research/specs/ethics_review.yaml`, `research/specs/knowledge_graph.yaml`, `EthicsReviewNode` class in `research/graph.py`, `KnowledgeGraphNode` class in `research/graph.py` (after T2 verified), `tests/unit/research/test_ethics_review.py` |

### §6.2 Experiment subgraph
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/experiment/graph.py`, `experiment/agents.py`, `experiment/state.py`, `experiment/line_tracer.py`, `experiment/harness.py`, `experiment/dagster_runner.py`, `experiment/template_copier.py`, `experiment/producers.py`, `experiment/report.py`, `models/experiment.py`, `models/experiment_output.py`, `config.py`, `configs/default.yaml`, `templates/dagster-experiment/src/pipeline/definitions.py`, `templates/dagster-experiment/src/pipeline/config_models.py`, `templates/dagster-experiment/src/pipeline/resources.py`, `templates/dagster-experiment/pyproject.toml`, `docker/experiment/Dockerfile` (drop tcp_server entry) |
| **Create** | **CORRECTED ralph-64**: NO `strategies/` directory exists — agent generates `assets/experiment/*` modules per-run. Stage 3-6 work creates EXAMPLES (canonical patterns the agent learns from) at `templates/dagster-experiment/examples/{tabular_classification,tabular_regression,timeseries,multimodal}_example.py`. Plus `templates/dagster-experiment/dvc.yaml` (Stage 6, at workspace root not src/pipeline/), `tests/unit/experiment/test_breadth_phase2.py`, `tests/unit/experiment/test_line_provenance.py`, `tests/unit/templates/test_stages_3_6.py`. Plus `assets/_common/` extensions for new `@asset_check` invariants. |
| **Delete** | `experiment/specs/ml_engineer.yaml`, `experiment/specs/experiment_judge.yaml`, `docker/experiment/tcp_server.py`, `InteractiveMLNode` class, `JudgeNode` class |

### §6.3 Writing subgraph
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/writing/graph.py`, `writing/agents.py`, `writing/state.py`, `writing/placeholder_scan.py`, `writing/specs/structure_architect.yaml`, `section_writer.yaml`, `intake.yaml`, `formatter.yaml`, `draft_writer.yaml`, `peer_reviewer.yaml`, `models/writing.py`, `runtime/paper_renderer.py`, `cli.py`, `config.py`, `configs/default.yaml` |
| **Create** | `tests/unit/writing/test_traceability_full.py`, `tests/unit/writing/test_acl_template.py` |
| **Delete** | none |

### §6.4 Review subgraph
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/review/graph.py`, `review/agents.py`, `review/state.py`, `review/cascade_aggregation.py`, `review/cascade_stages.py`, `review/novelty_aggregation.py`, `review/specs/editorial_synthesizer.yaml`, `models/review.py`, `models/cascade.py`, `models/persona_review.py`, `config.py`, `configs/default.yaml` |
| **Create** | `tests/unit/review/test_cascade_phase2.py` |
| **Delete** | none — legacy reviewer YAMLs (`domain_reviewer.yaml`, `methodology_reviewer.yaml`, `perspective_reviewer.yaml`) kept behind `legacy_reviewers` flag |

### §6.5 Integrity subgraph
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/integrity/graph.py`, `integrity/agents.py`, `integrity/state.py`, `integrity/specs/integrity_verification.yaml`, `tools/integrity_tools.py`, `models/integrity.py`, `models/ethics.py` |
| **Create** | `src/academic_pipeline/integrity/ethics_checklist.py` (the `EthicsChecklistNode` lives here), `src/academic_pipeline/integrity/specs/ethics_reviewer.yaml` (NEW agent yaml per Spec 8 design doc — note name is `ethics_reviewer` with -er, NOT `ethics_review`; output_type is `PromptedOutput[EthicsChecklist]`), `tests/unit/integrity/test_ethics_checklist.py` |
| **Delete** | none (legacy `EthicsReviewNode` removal lives in §6.1) |

### §6.6 Recovery
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/cli.py`, `recovery/watchdog.py`, `recovery/supervisor.py`, `runtime/events.py`, `runtime/dashboard.py` |
| **Create** | `docs/architecture/recovery.md`, additional tests in `tests/integration/test_hang_recovery_e2e.py` |
| **Delete** | none |

### §6.7 Rendering
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/runtime/paper_renderer.py`, `runtime/citation_resolver.py`, `tools/rendering/latex_compiler.py`, `tools/bibliography/doi.py`, `tools/bibliography/citations.py`, `tools/bibliography/bibtex.py`, `writing/specs/formatter.yaml`, `templates/dagster-experiment/src/pipeline/_publication_style.py` |
| **Create** | `templates/pandoc/acl/` (the `.cls` + supporting files — already uncommitted), `templates/pandoc/acl-header.tex` (already uncommitted), `tests/unit/runtime/test_citation_resolver_pandoc.py` (already uncommitted), `tests/unit/runtime/test_paper_renderer_captions.py` (already uncommitted), `tests/unit/tools/test_citations.py`, `tests/integration/test_acl_e2e.py`, `docs/architecture/rendering.md` |
| **Delete** | `scripts/rerender_latest.py` (broken — imports deleted `figure_executor`) |

### §6.8 Dashboard + Events
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/runtime/events.py`, `runtime/dashboard.py`, `runtime/throttle.py` |
| **Create** | additional tests in `tests/unit/runtime/test_dashboard.py` (or new `test_events_v2.py`); React dashboard v2 location TBD (T5 — out of `src/`, deferred non-blocking) |
| **Delete** | none |

### §6.9 Persistence + AgentCache
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/persistence.py`, `tools/agent_cache.py`, `cli.py` |
| **Create** | `tools/cleanup_state.py` (project-root tools/, not src/), additional tests in `tests/unit/test_persistence.py` |
| **Delete** | none |

### §6.10 Traceability
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/traceability/dialogue.py`, `traceability/context_spec.py`, `traceability/substitution.py`, `traceability/validators.py`, `traceability/notes_appendix.py`, `traceability/code_appendix.py`, `traceability/errors.py`, `runtime/paper_renderer.py`, `tools/rendering/latex_compiler.py`, plus per-agent ContextSpec migrations in `writing/specs/draft_writer.yaml`, `section_writer.yaml`, `review/specs/editorial_synthesizer.yaml`, `peer_reviewer.yaml`, the 3 persona reviewer YAMLs, `experiment/specs/result_analyzer.yaml` |
| **Create** | `docs/architecture/traceability.md`, `tests/unit/traceability/test_phase2.py` |
| **Delete** | none |

### §6.11 Quality Gate
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/runtime/evaluator.py`, `runtime/hard_vetos.py`, `runtime/score_trajectory.py`, `research/specs/independent_verifier.yaml`, `writing/specs/figure_verifier.yaml`, `config.py`, `configs/default.yaml` |
| **Create** | `tests/unit/runtime/test_evaluator_phase2.py` |
| **Delete** | none |

### §6.12 Config + SDK Surface
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/config.py`, `configs/default.yaml`, `sdk/pipeline.py`, `sdk/result.py`, `sdk/events.py`, `__init__.py`, `pyproject.toml`, `VERSION`, `README.md`, `CHANGELOG.md` |
| **Create** | `tools/check_version_consistency.py`, `examples/run_with_acl_template.py`, `examples/run_with_breadth_mode.py`, `examples/inspect_cascade_verdict.py`, `examples/replay_from_events_jsonl.py`, `docs/architecture/skills.md`, `docs/architecture/sdk.md`, `tests/unit/sdk/test_observe.py`, additional tests in `tests/unit/test_config.py` (skill-pack loading) |
| **Delete** | none |

### §6.13 Observability
| Action | Files |
|---|---|
| **Modify** | `src/academic_pipeline/observability.py`, `runtime/trace_logger.py`, `runtime/events.py` |
| **Create** | `docs/architecture/observability.md`, additional tests in `tests/unit/test_observability.py` |
| **Delete** | none |

### §6.14 CI / Release Pipeline
| Action | Files |
|---|---|
| **Modify** | `.github/workflows/ci.yml`, `.github/workflows/publish.yml` (audit + likely rewrite per T2), `Makefile` (if new test targets needed), `pre-commit-config.yaml` (if new hooks added) |
| **Create** | `docs/architecture/release.md` |
| **Delete** | none (publish.yml may be wholly rewritten — net delta is modify) |

### §6.15 Output Verification + LLM-as-Judge
| Action | Files |
|---|---|
| **Modify** | `pyproject.toml` (add `judgy>=0.1` dev dep), `Makefile` (add `test-regression`, `realign` targets) |
| **Create** | `tests/fixtures/golden/<topic_slug>/{topic.txt,expected.yaml,reference_paper.bib,metrics.yaml}` × 5 fixture topics, `tests/fixtures/labeled_traces/<failure_mode>/{train,dev,test}.jsonl` × 6 failure modes, `tools/output_assertions.py`, `src/academic_pipeline/evaluation/__init__.py`, `evaluation/splits.py`, `evaluation/alignment.py`, `evaluation/correction.py`, `evaluation/regression.py`, `evaluation/estimate.py`, `evaluation/overlap_check.py`, `evaluation/judges/__init__.py`, `evaluation/judges/registry.py`, `evaluation/judges/specs/{hedge_language,thesis_coherence,persona_tone_mismatch,citation_orphan,fabricated_numeric,imrad_completeness}.yaml`, `evaluation/judges/{hedge_language,thesis_coherence,...}.py` (Python wrappers, 6 files), `tests/unit/tools/test_output_assertions.py`, `tests/unit/evaluation/test_splits.py`, `test_alignment.py`, `test_correction.py`, `test_judges.py`, `docs/v2.5.0-spot-review.md`, `docs/architecture/evaluation.md`, `docs/evaluation/failure-modes.md` |
| **Delete** | none |

### Cross-cutting deletions audit

These files are deleted by Phase 2 wirings. The loop must verify each is gone after the corresponding component lands, AND that no other module imports them:

| Path | Killed by | Cross-import check |
|---|---|---|
| `src/academic_pipeline/research/specs/ethics_review.yaml` | §6.1.T6 | grep for `"ethics_review"` agent key in `research/agents.py` registry — must be removed |
| `src/academic_pipeline/research/specs/knowledge_graph.yaml` | §6.1.T7 | grep for `"knowledge_graph"` agent key + `KnowledgeGraphNode` class references |
| `src/academic_pipeline/experiment/specs/ml_engineer.yaml` | §6.2.T7 | grep for `"ml_engineer"` agent key |
| `src/academic_pipeline/experiment/specs/experiment_judge.yaml` | §6.2.T7 | grep for `"experiment_judge"` agent key |
| `docker/experiment/tcp_server.py` | §6.2.T7 | grep `Dockerfile` for `COPY tcp_server` and `CMD` referring to it |
| `scripts/rerender_latest.py` | §6.7.T8 | grep for any Makefile target invoking `python scripts/rerender_latest.py` |

After each deletion, run: `uv run ruff check src/academic_pipeline/ tests/ && uv run pyright src/academic_pipeline/` — broken imports should fail-fast at the type-check.

---

## 16. Cross-Component Data Handoff Map

Every Phase 2 data artifact, where it is produced, where it is consumed, and which config flag gates production. **Class names verified against `src/academic_pipeline/models/` at HEAD (2026-05-06).**

When the loop adds or modifies a Phase 2 data artifact, it must:
1. Confirm the producer is wired to write the artifact into pipeline state.
2. Confirm every consumer reads it from the right field name.
3. Confirm the gating flag is honored — if the flag is off, the artifact must be `None` (not raise) and consumers must tolerate the `None`.

| # | Artifact | Pydantic class | Source file | Producer | Consumers | Gating flag | State field |
|---|---|---|---|---|---|---|---|
| 1 | Development chain | `DevelopmentChain` with `milestones: list[Milestone]` (ordered, 5-15 nodes) + `edges: list[ChainEdge]` + `terminal_unsolved_problem: str` (1-3 sentences, the gap our paper addresses — drives the thesis). Each `Milestone` has `milestone_id` (M1, M2, ...), `milestone_type: MilestoneType` (5 values: `concept_intro` / `method_ext` / `benchmark` / `refutation` / `application`), `year: int`, `key_paper_doi: str \| None`, `key_paper_title: str`, `one_sentence_advance: str`. Each `ChainEdge` has `from_milestone`, `to_milestone`, `relation: EdgeRelation` (4 values: `extends` / `refutes` / `supersedes` / `applies_to`). Verified `models/chain.py` + Spec 2 design doc. | `models/chain.py` | §6.1 **`ChainOfIdeasNode`** — ONE node that calls TWO agents (`chain_of_ideas_extractor` then `thesis_extractor`), per Spec 2 design doc. PRD ralph-1..36 had implied two separate nodes — corrected. | §6.3 `StructureArchitect`, `ArgumentBuilder`; §6.4 cascade Stage C | `chain_of_ideas_enabled` | `ResearchState.chain` (verified `research/state.py:42`) |
| 2 | Thesis statement | `ThesisStatement` with 3 fields: `claim: str` (1-2 sentence assertion the paper proves), `novelty_dimension: Literal["new_concept", "method_extension", "new_application", "refutation"]` (4 values — **NOTE: different from Spec 4's `ClaimNoveltyDimension` which has 5 values `new_concept`/`new_method`/`new_application`/`new_dataset`/`new_result`**; two distinct novelty taxonomies), `grounded_in_milestone: str` (milestone_id this thesis builds on). Verified `models/chain.py:72` + Spec 2 design doc. | `models/chain.py` | §6.1 same `ChainOfIdeasNode` second LLM call (`thesis_extractor` agent) — produces ThesisStatement from DevelopmentChain.terminal_unsolved_problem | §6.3 `DraftWriter`, `SectionWriter`, `StructureArchitect`; §6.4 `independent_verifier`; §6.11 quality gate; §6.15 `thesis_coherence` judge | `chain_of_ideas_enabled` | `ResearchState.thesis` (verified `research/state.py:43`) |
| 3 | Novelty gate verdict | `NoveltyGateResult` with `verdict: NoveltyVerdict` (3 values: `"novel"` / `"partial"` / `"redundant"` per `research/novelty_gate.py:130`) + `max_similarity: float` + `nearest_neighbors: list[NeighborPaper]` (top 10) + `differentiation_paragraph: str \| None` (only set when verdict=PARTIAL per Spec 3 design — currently NOT IMPLEMENTED at HEAD; §6.1.T5 must add this OR change to RQ-refinement design) | `models/novelty_gate.py` | §6.1 `NoveltyGateNode` (between intake and research; lives at `research/novelty_gate.py` as a function `compute_novelty_gate()`, not a class) | §6.1 `ResearchQuestionNode` for partial-verdict refinement; §6.8 `events.jsonl` `novelty_gate_verdict` | `novelty_gate_enabled` | `PipelineState.novelty_gate_result` |
| 4 | Persona review outputs (×3) | `PersonaReviewOutput` (with `PersonaSpec`, `ReviewFinding[]`). Each `PersonaSpec` has 3 axes: `commitment` (`thorough` \| `superficial`), `intention` (`skeptical_gatekeeper` \| `applied_practitioner` \| `enthusiastic_advocate` \| `domain_purist`), `knowledgeability` (`deep_in_field` \| `adjacent_field` \| `novice`) — verified `models/persona_review.py:23-49`. v2.5.0 wires only 3 of the 24 possible combinations | `models/persona_review.py` | §6.4 `ParallelReviewerNode` (3 persona agents: `senior_gatekeeper_reviewer`, `applied_practitioner_reviewer`, `methodology_purist_reviewer`) | §6.4 cascade Stage C (methodology gate uses senior_gatekeeper + methodology_purist short-circuit); §6.4 `EditorialSynthesizerNode` | `persona_reviewers_enabled` | `ReviewState.persona_reviews` |
| 5 | Point-wise novelty report | `NoveltyReport` with `ContributionClaim[]` + `ClaimAssessment[]`. Per-claim `ClaimVerdict` enum has 3 values: `redundant` / `partial_overlap` / `novel`. Per-claim `ClaimNoveltyDimension` enum has 5 values: `new_concept` / `new_method` / `new_application` / `new_dataset` / `new_result`. **Overall verdict is `REJECT_NOVELTY` if ANY claim verdict is `redundant`** (per Spec 4 design doc); `partial_overlap` is a warning, not a rejection (Non-goal #3). Verified `models/novelty_report.py:78` + design doc | `models/novelty_report.py` | §6.4 `PointWiseNoveltyReviewerNode` (`claim_extractor` agent extracts claims; `claim_novelty_assessor` agent searches Semantic Scholar for top-5 nearest prior works per claim) | §6.4 cascade Stage B (uses `REJECT_NOVELTY` to short-circuit) | `pointwise_novelty_enabled` | `ReviewState.novelty_report` (verified `review/state.py:43`) |
| 6 | Cascade verdict | `CascadeResult` with `stages: list[StageResult]` — **always 4 entries** in stage order: NUMERICAL_GROUNDING, NOVELTY, METHODOLOGY, **NARRATIVE** (verified `docs/superpowers/specs/2026-05-03-cascaded-reviewer-design.md`); each `StageResult.verdict: StageVerdict` is one of `pass` / `short_circuit_reject` / `skipped` (because earlier stage rejected) / `not_run` (because feature flag off) | `models/cascade.py` | §6.4 `CascadedReviewNode` (composes Specs 1+4+5; produces 4 stages of which only A/B/C short-circuit per `cascade_short_circuit_on_stage_*` config — Stage D is the final leaf stage with no short-circuit needed) | §6.4 `EditorialSynthesizerNode` (enforces verdict in Phase 2 — currently reads but does not enforce); §6.5 `FinalIntegrityNode` (Phase 2); §6.11 `independent_verifier`; §6.8 `events.jsonl` `cascade_verdict`; §6.15 metric input | `cascaded_review_enabled` | `ReviewState.cascade_result` |
| 7 | Numerical claim audit | `ClaimAuditReport` (with `ClaimAuditFinding[]`) | `models/cascade.py` | §6.4 `numerical_claims_auditor` agent (Stage A of cascade) | §6.4 cascade aggregation; §6.7 `latex_compiler` (DOI gate cross-check); §6.15 `fabricated_numeric` judge | implicit when `cascaded_review_enabled` | `CascadeResult.claim_audit` |
| 8 | Ethics checklist | `EthicsChecklist` with `items: list[ChecklistItem]` (exactly 12 items per Spec 8 design doc) + `overall_verdict: Literal["pass", "pass_with_waivers", "block"]` + `blocker_items: list[str]`. Each `ChecklistItem` has `name` (snake_case stable), `answer: bool`, `justification: str` (min 20 chars), `waiver: str \| None` (if answer=False, an explicit waiver OR None means blocking). **The 12 standard item names** (verified `docs/superpowers/specs/2026-05-03-checklist-ethics-design.md` STANDARD_ITEMS list): `human_subjects_disclosed`, `irb_approval_documented`, `informed_consent_documented`, `data_provenance_traced`, `data_use_license_compliant`, `coi_disclosed`, `structural_coi_absent`, `ai_assistance_disclosed`, `reproducibility_artifacts_present`, `phi_pii_absent`, `demographic_representation_addressed`, `potential_misuse_acknowledged`. Loop must use these exact names. | `models/ethics.py` | §6.5 `EthicsChecklistNode` invoking new `ethics_reviewer` agent (replaces freeform `EthicsReviewNode` from §6.1) | §6.5 `IntegrityVerdict` aggregation (`overall_verdict="block"` blocks finalize); §6.7 `notes_appendix` (auto-attached); §6.8 `events.jsonl` `ethics_checklist_result` | `ethics_checklist_enabled` (verified `docs/superpowers/specs/2026-05-03-checklist-ethics-design.md:148`) | **TO BE ADDED in §6.5.T1**: `IntegrityState.ethics_checklist: EthicsChecklist \| None = None`. Verified absent at `integrity/state.py` HEAD — field does not exist yet, Phase 2 wiring creates it. |
| 9 | Trace token resolution table | `NumericalStore` (with `NumericalProduct[]`). Each `NumericalProduct` has 9 fields per `models/numerical.py`: `label` (snake_case, unique within store), `value` (rendered string e.g. `"23.5"`, `"p<0.001"`, `"0.84 [0.71-0.97]"`), `unit` (e.g. `"%"`, `"mg/dL"`, `None`), `formula` (human-readable e.g. `"mean of column X for diabetic subset"`), `source_run_id`, `source_step` (`"experiment"` / `"research_synthesis"` / `"integrity"`), `source_artifact` (path under `output/<run-id>/`), `source_code_line` (e.g. `"analysis.py:42"`, populated by `experiment/line_tracer.py`), `context` (1-sentence description for Notes appendix) | `models/numerical.py:29` | §6.10 `traceability/substitution.py::substitute_tokens(text, store, output_format="latex"\|"html", section_name=None)`. **Verified ralph-55**: LaTeX path emits `\hyperlink{num_<label>}{<value>}`, HTML path emits plain value (no hyperlink). Raises `SubstitutionFailure(TRC003)` on unresolved label. Populated upstream by `AnalysisNode` per the inline doc in `writing/state.py` | §6.3 `paper_renderer` (substitutes tokens at compile via the verified function above); §6.4 cascade Stage A (asserts every numeric has a token); §6.7 `latex_compiler` (rejects unresolvable; emits Notes appendix with `\hypertarget{num_<label>}{}` per entry + Code appendix with `\hypertarget{code_<run>_<line>}{}` at producing lines); §6.15 `fabricated_numeric` judge | `traceability_mode != "off"` (full coverage requires `"full"` — `partial` enables store + validator + Notes appendix; `full` adds dialogue + curated context + Code appendix) | `WritingState.numerical_store: NumericalStore = field(default_factory=NumericalStore)` (verified `writing/state.py`); also dumped to `output/<run-id>/03-writing/trace_tokens.json` for postmortem |
| 10 | Per-agent context spec | `ContextSpec` (frozen Pydantic, 2 fields: `allowed_products: list[str]`, `allowed_numerical_labels: list[str] \| Literal["all"]`). Class verified at `traceability/context_spec.py:15-25` (only 25 lines — class def only, NO global per-agent instances). | `traceability/context_spec.py` (class def) + per-agent module (instances) | §6.10.T2/T3 — define per-agent INSTANCES (e.g., `DRAFT_WRITER_CONTEXT_SPEC = ContextSpec(...)`) in each agent's home module. The class itself stays at `traceability/context_spec.py`. | `runtime/context.py::build_curated_context(state, spec)` builds the prompt context (raises `TypeError` if spec is not a ContextSpec instance — no duck typing) | implicit per-agent | injected via PydanticAI `RunContext` deps |
| 11 | Design bundle (N alternative experiments) | **4 Pydantic models** per Spec 7 design doc: (a) `DesignBundle` with `alternatives: list[DesignAlternative]` (N entries, default 4); each `DesignAlternative` wraps an `ExperimentDesign` + `rationale: str`; (b) `DesignScore` per design with **5-criterion rubric**: `data_availability_score` + `methodological_fit_score` + `expected_discriminative_power` + `risk_score` (each 1-10) + `overall_score` (weighted composite) + `selection_rationale`; (c) `SelectedDesigns` with `selected: list[DesignAlternative]` (top K, default 2) + `not_selected: list[DesignAlternative]` + `scores: list[DesignScore]` (all N scores); (d) `DesignComparison` with `selected_results: dict[str, ExperimentResults]` + `comparison_table: str` (markdown) + `discussion_paragraph: str` (to be inserted in paper's Discussion section) + `chosen_design_id: str` (whose results become primary findings). Verified `models/experiment.py`; imports in `experiment/state.py:9` | `models/experiment.py` | §6.2 `ExperimentDesignBundleNode` (note: spec doc says renamed from `ExperimentDesignNode`, but actual codebase per iter 26 has BOTH coexisting — single-design path stays for non-breadth mode; bundle path is parallel) using `experiment_designer_bundle` + `design_comparator` + `design_scorer` agents | §6.2 K-parallel `DagsterRunNode` (Phase 2 fans out top K); §6.8 `events.jsonl` `design_bundle_scores` | `exploration_breadth_enabled` | `ExperimentState.design_bundle`, `ExperimentState.selected_designs`, `ExperimentState.design_comparison` (all 3 verified existing in `experiment/state.py:55-57` for Phase 1) |
| 12 | Multi-design analysis | `ExperimentResults` (extended to `list[ExperimentResults]` plus comparative aggregation) | `models/experiment.py` | §6.2 `AnalysisNode` (Phase 2 — accepts a list of results from K parallel runs) | §6.3 `DraftWriter`, `SectionWriter`, `StructureArchitect` (consumes list when present, single result when not) | `exploration_breadth_enabled` | `ExperimentState.results` (becomes `list[ExperimentResults]`) |
| 13 | Code appendix | rendered LaTeX section text | `traceability/code_appendix.py::generate_code_appendix(runs) -> str`. **Verified ralph-55**: uses `_CodeRun` Protocol (structural typing — accepts `StubCodeRun` in tests or `ExperimentRun` in production). Required Protocol attrs: `run_id: str`, `code: str`, `code_filename: str`, `producing_lines: tuple[int, ...]`. Format per run: `\section{Code: <filename>}\begin{python}<body with \hypertarget{code_<run_id>_<line>}{} prefixed at each producing_lines entry>\end{python}`. **Empty-string return** when no runs — caller MUST NOT include the section in the manuscript when empty. | §6.10 at render time | §6.7 `latex_compiler` auto-attaches | `traceability_mode == "full"` | runtime artifact in `output/<run-id>/03-writing/appendix_code.tex` |
| 14 | Notes appendix | rendered LaTeX section text | `traceability/notes_appendix.py::generate_notes_appendix(store: NumericalStore, cited_labels: set[str]) -> str`. **Verified ralph-55**: per-item format `\item \hypertarget{num_<label>}{}\textbf{<value> <unit>} --- <context>. Computed as: <formula>. See \hyperlink{code_<run>_<line>}{<source_code_line>}.` Wrapper `\section{Calculation Notes}\begin{itemize}...\end{itemize}`. `source_code_line` format `"analysis.py:42"` → split on `:` to get `<line>` for hyperlink. **Empty-string return** when no cited_labels. **Silently skips labels not in store** (`if label not in store.products: continue`) — opportunity for fail-loud refactor (currently a label could be cited in body but missing from notes; v2.6.0 candidate). | §6.10 at render time | §6.7 `latex_compiler` auto-attaches | `traceability_mode == "full"` | runtime artifact in `output/<run-id>/03-writing/appendix_notes.tex` |
| 15 | Recovery event | typed `RecoveryEvent` (to be added in §6.8.T1) | `runtime/events.py` (new type) | §6.6 watchdog L4 + L1/L2/L3 layers via `Heartbeat`/`bounded_run`/etc. | §6.8 dashboard renderer; §6.13 Logfire span | always (recovery system always on) | `events.jsonl` line per fire |
| 16 | Copilot comments at named checkpoints | `dict[str, str]` (no class — runtime) | n/a | §6.10 `traceability/copilot.py::copilot_checkpoint(*, name, summary, timeout_s=60, enabled=True, stdin_reader=_default_stdin_reader)` at 3 named checkpoints (`post_intake`, `post_experiment_design`, `post_first_draft`). Verified ralph-54: 60s default stdin timeout (configurable); whitespace-only input treated as empty; returns None on disabled/timeout/empty. **Quantified benefit per data-to-paper**: 2-3 single-sentence comments turn 90% error rate → 10-20% on complex tasks. Massive reliability lever for near-zero human effort. `StdinReader` Type alias accepts both async and sync callables (test ergonomics). | §6.10 dialogue helper, §6.7 `notes_appendix` (auto-attached) | `copilot_enabled` | `PipelineState.copilot_comments: dict[str, str]` (verified `pipeline/state.py`) |
| 17 | Material passport (per-artifact provenance + verification record) | `MaterialPassport` (7 fields: `origin_skill: str`, `origin_date: datetime` (default now-UTC), `verification_status: VerificationStatus` (Literal `"VERIFIED"`/`"UNVERIFIED"`/`"STALE"` per `models/shared.py:85`, default `"UNVERIFIED"`), `version_label: str`, `integrity_pass_date: datetime \| None`, `content_hash: str \| None`, `upstream_dependencies: list[str]`) plus 2 derived properties: `is_stale` (returns True if integrity_pass_date is None or older than `PASSPORT_FRESHNESS_HOURS=24` per `models/shared.py:87`), `can_skip_pre_review_integrity` (returns True iff `verification_status=="VERIFIED" and not is_stale`). Verified `models/integrity.py:245-270`. | `models/integrity.py` | populated by §6.5 integrity subgraph after a successful pass; used to skip pre-review integrity when passport is fresh + verified | §6.5 PreIntegrityNode (skip if `can_skip_pre_review_integrity`); §6.7 manuscript metadata; §6.8 events.jsonl `integrity_pass` event (TBD) | always (no flag — core durability layer) | `PipelineState.material_passport: MaterialPassport \| None = None` (verified `pipeline/state.py`) |

**Dual-layer state caveat.** Many of the artifacts above live on BOTH the subgraph state (e.g., `ResearchState.chain`) AND the top-level `PipelineState` (e.g., `PipelineState.chain`). The pipeline orchestrator copies the subgraph output into `PipelineState` after the subgraph completes (verified via `pipeline/nodes.py` handoff logic). When in doubt about which layer to read, prefer `PipelineState` for cross-subgraph reads (after the producer completes) and `<Subgraph>State` for intra-subgraph reads (during the producer's own execution). Phase 2 wirings that add new artifacts MUST add them to BOTH layers to maintain consistency.

Verified PipelineState mirrors at HEAD (`pipeline/state.py`):
- `PipelineState.chain` (mirrors `ResearchState.chain`)
- `PipelineState.thesis` (mirrors `ResearchState.thesis`)
- `PipelineState.novelty_gate_result` (sole owner — produced before research subgraph fires)
- `PipelineState.novelty_report` (mirrors `ReviewState.novelty_report`)
- `PipelineState.persona_reviews` (mirrors `ReviewState.persona_reviews`)
- `PipelineState.cascade_result` (mirrors `ReviewState.cascade_result`)
- `PipelineState.numerical_store` (mirrors `WritingState.numerical_store`)
- `PipelineState.copilot_comments` (sole owner — orthogonal to subgraphs)

### Field-name-stability promise

Once Phase 2 lands, the **state field names listed in the rightmost column become public API for any cross-process tooling** (e.g., the `Pipeline.observe(callback)` SDK surface from §6.12.T2, or external dashboards that read `events.jsonl`). Renaming any of these fields after v2.5.0 is a SemVer-breaking change and must wait for v3.0.0.

### Anti-pattern: artifact field name drift

A common drop-pattern: producer writes to `state.thesis` but consumer reads `state.thesis_statement`. Both compile, both type-check (with `Optional[]` defaults), and the bug only surfaces when the consumer's behavior depends on a non-None value. Mitigation: every consumer site MUST do `assert state.thesis_statement is not None, "thesis_statement missing — chain_of_ideas_enabled flag broken?"` at the top of its handler when the relevant flag is on. This converts a silent semantic gap into a loud assertion error.

### Naming corrections

The earlier PRD revisions referred to a few artifacts with informal names that don't match the actual Pydantic classes. Use the verified names from this section going forward:

| Earlier informal name (avoid) | Verified class (use) | Source |
|---|---|---|
| `Thesis` | `ThesisStatement` | `models/chain.py:72` |
| `ChainOfIdeas` | `DevelopmentChain` | `models/chain.py:62` |
| `EthicsReport` | `EthicsChecklist` | `models/ethics.py:62` |
| `NoveltyVerdict` | `NoveltyGateResult` | `models/novelty_gate.py:33` |
| `Cascade` (bare) | `CascadeResult` | `models/cascade.py:60` |
| `PointWiseNoveltyReport` (no such class) | `NoveltyReport` | `models/novelty_report.py:78` |
| `state.thesis_statement` (state field) | `state.thesis` | `research/state.py:43` |
| `state.development_chain` (state field) | `state.chain` | `research/state.py:42` |
| `state.pointwise_novelty_report` (state field) | `state.novelty_report` | `review/state.py:43` |

---

## 17. Error-Code Namespaces

Per the spec roadmap convention ("Every spec defines its own `error_code` namespace for postmortem grep"), every Phase 2 component owns a 3-letter prefix and a stable numeric code per failure type. Codes are emitted into `events.jsonl` records and Logfire span attributes, so postmortems can grep by namespace + code without parsing free-form text.

**Existing namespace at HEAD (verified):** TRC (codes TRC000–TRC006 in `src/academic_pipeline/traceability/errors.py`).

**v2.5.0 namespace registry (allocate as Phase 2 wirings land):**

| Prefix | Component | Spec | Source file (target) | Reserved range | Example codes |
|---|---|---|---|---|---|
| **TRC** | §6.10 Traceability | Spec 1 | `traceability/errors.py` (exists) | TRC000–TRC099 | TRC001 NumericValidatorRetry, TRC002 NumericValidatorAbort, TRC003 SubstitutionFailure, TRC004 StoreIntegrityError, TRC005 CopilotTimeout, TRC006 DialogueExhaustion |
| **COI** | §6.1 Research (Spec 2 Phase 2) | Spec 2 | `research/errors.py` (new) | COI000–COI099 | COI001 ChainExtractionFailed, COI002 ThesisAbsent, COI003 ChainCycleDetected, COI004 OrphanMilestone |
| **NOV** | §6.1 Research / Novelty Gate | Spec 3 | `research/novelty_gate.py` (extend) | NOV000–NOV099 | NOV001 SemanticScholarUnavailable, NOV002 SimilarityAboveTauBlock, NOV003 SoftWarnTriggered, NOV004 ZeroNeighborsReturned |
| **PWN** | §6.4 Review (Spec 4) | Spec 4 | `review/errors.py` (new) | PWN000–PWN099 | PWN001 ClaimExtractionEmpty, PWN002 NeighborsZero, PWN003 SimilarityBelowFloor, PWN004 ReportSchemaInvalid |
| **PRR** | §6.4 Review (Spec 5) | Spec 5 | `review/errors.py` (shared) | PRR000–PRR099 | PRR001 PersonaUnknown, PRR002 ReviewFindingMissing, PRR003 ReviewerTimedOut |
| **CAS** | §6.4 Review (Spec 6) | Spec 6 | `review/cascade_aggregation.py` (extend) | CAS000–CAS099 | CAS001 StageANumericFail, CAS002 StageBNoveltyFail, CAS003 StageCMethodologyFail, CAS004 EditorialOverrideAttempt (Phase 2 forbidden), CAS005 StageInputMissing, **CAS006 StageDNarrativeWeak** (verified ralph-31: cascade has 4 stages, Stage D = NARRATIVE) |
| **EBM** | §6.2 Experiment (Spec 7) | Spec 7 | `experiment/errors.py` (new) | EBM000–EBM099 | EBM001 DesignBundleEmpty, EBM002 DesignScoreInvalid, EBM003 ParallelDagsterFail, EBM004 KExceedsBundleSize, EBM005 AggregationSchemaMismatch |
| **ETH** | §6.5 Integrity (Spec 8) | Spec 8 | `integrity/ethics_validator.py` (extend) | ETH000–ETH099 | ETH001 ChecklistItemUnscored, ETH002 OverrideDirectiveMissing, ETH003 PRISMAConfigInvalid, ETH004 EthicsBlockingFail |
| **REC** | §6.6 Recovery | — | `recovery/errors.py` (new — currently inline) | REC000–REC099 | REC001 KeepaliveSocketUnavailable, REC002 BoundedRunTimeout, REC003 HeartbeatThreadDied, REC004 WatchdogStaleEvents, REC005 ThreeStrikesAbort, REC006 PGIDFileStale |
| **REN** | §6.7 Rendering | — | `runtime/rendering_errors.py` (new) | REN000–REN099 | REN001 DOICrossRefFail, REN002 AuthorsYamlMissing, REN003 TitleExceeds12Words, REN004 TectonicCompileFail, REN005 LongtableFilterUnavailable, REN006 ACLClassMissing |
| **DSH** | §6.8 Dashboard + Events | — | `runtime/dashboard.py` (extend) | DSH000–DSH099 | DSH001 SchemaVersionMismatch, DSH002 EventsFileTruncated, DSH003 ThrottleFloodDropped, DSH004 UnknownEventType |
| **PRS** | §6.9 Persistence + AgentCache | — | `persistence.py` (extend) | PRS000–PRS099 | PRS001 IncompatibleStateError, PRS002 SchemaVersionAbsent, PRS003 AgentCacheCorrupt, PRS004 ResumeNoTargetNode, PRS005 SnapshotMidNode |
| **QGT** | §6.11 Quality Gate | — | `runtime/evaluator.py` (extend) | QGT000–QGT099 | QGT001 RubricMissing, QGT002 IterationsExhausted, QGT003 HedgeLanguageDetected, QGT004 MissingTraceTokenInClaim, QGT005 PerNodeThresholdAbsent |
| **CFG** | §6.12 Config + SDK | — | `config.py` (extend) | CFG000–CFG099 | CFG001 ConfigPrecedenceViolation, CFG002 LegacyFlagWithNewFlag, CFG003 SkillsDirAbsent, CFG004 ExampleScriptDryRunFail, CFG005 VersionMismatch |
| **OBS** | §6.13 Observability | — | `observability.py` (extend) | OBS000–OBS099 | OBS001 LogfireConfigureFail, OBS002 InstrumentationAlreadyApplied, OBS003 SpanEnrichmentMissingField, OBS004 LogRotationFailed |
| **CIR** | §6.14 CI / Release | — | `tools/check_version_consistency.py` (new — see §6.12.T6) | CIR000–CIR099 | CIR001 PyprojectVersionDrift, CIR002 PublishYmlMissing, CIR003 PreCommitFail, CIR004 TestMediumDockerAbsent, CIR005 PypiTokenMissing |
| **EVL** | §6.15 Output Verification (framework) | — | `evaluation/errors.py` (new) | EVL000–EVL099 | EVL001 SplitOverlapDetected, EVL002 JudgeBelowTPRFloor, EVL003 JudgeBelowTNRFloor, EVL004 BootstrapDegenerateJudge, EVL005 CIWidthExceedsThreshold, EVL006 SpotReviewBoxesIncomplete, EVL007 GoldenFixtureMalformed |
| **FBR** | §6.15 per-failure-mode (subset of EVL) | — | `evaluation/judges/registry.py` | FBR000–FBR099 | FBR001 HedgeLanguagePresent, FBR002 ThesisIncoherent, FBR003 PersonaToneMismatch, FBR004 CitationOrphan, FBR005 FabricatedNumeric, FBR006 IMRaDIncomplete |

### Allocation rules

1. **Three-letter uppercase prefix.** No more, no less.
2. **Three-digit zero-padded suffix.** `TRC001` not `TRC1` or `TRC0001`.
3. **Each namespace owns a contiguous range.** Default `XYZ000–XYZ099`. If a namespace exceeds 100 codes, allocate `XYZ100–XYZ199`, etc., and document.
4. **Code-to-class binding lives in one file per namespace.** The file path is in the table above.
5. **Codes are immutable once shipped.** Renaming `CAS001` to `CAS002` after release is forbidden — postmortems and Logfire queries depend on stable identifiers. To deprecate, mark the class with `# DEPRECATED: do not raise; kept for historical grep` and allocate a new code.
6. **Every raised error MUST carry its code.** Either via class attribute `error_code = "XYZ###"` (preferred — see `traceability/errors.py` pattern) or as a kwarg to the base exception.
7. **Events.jsonl + Logfire spans MUST tag the code.** When emitting an event for a failure, include `error_code` as a top-level JSONL field and as a Logfire span attribute.

### Loop directive

When the loop encounters or introduces a new failure mode in a Phase 2 wiring, it MUST:
1. Identify which namespace owns the failure (use the table above).
2. Allocate the next sequential code in that namespace.
3. Define the exception class in the namespace's source file with `error_code` attribute.
4. Wire emission to events.jsonl + Logfire span.
5. Add a row to this table in the same PR. **Do not invent ad-hoc strings like `"writing_failed"` or `"review_error"`.**

---

## 18. events.jsonl Schema

`events.jsonl` is the single source of truth for pipeline progress (per §6.8). Every consumer (the `runtime/dashboard.py` renderer, the React dashboard v2, external `Pipeline.observe()` subscribers, the regression suite) reads this file. Schema drift breaks every consumer. **This appendix is the canonical schema.**

### 18.1 Universal envelope

Every record is one JSON object per line, terminated with `\n`. Two fields are always present:

| Field | Type | Required | Notes |
|---|---|---|---|
| `ts` | float | yes | Unix epoch seconds, fractional. Captured at emit time via `time.time()`. Monotonic within a single run; not guaranteed monotonic across resumes. |
| `type` | string | yes | The event type (one of the values listed in 18.2). Stable across versions; new types are additive only. |

Plus one optional schema-version marker emitted as the **first record** of every run (added in §6.8.T3):

| Field | Type | Required | Notes |
|---|---|---|---|
| `version` | string | first record only | semver-like (e.g., `"2.5.0"`). Renderers reject mismatched majors with `DSH001 SchemaVersionMismatch`. |

### 18.2 Event types

#### Existing at HEAD (verified via real `events.jsonl` samples 2026-05-06)

```json
// pipeline_start
{"ts": 1777663557.176621, "type": "pipeline_start",
 "run_id": "run-0501-1225_200b",
 "topic": "Predicting 30-day hospital readmission risk...",
 "resumed": false}

// stage_change
{"ts": 1777663557.231999, "type": "stage_change",
 "stage": "research", "previous": null}

// node_complete
{"ts": 1777663557.194601, "type": "node_complete",
 "stage": "", "node": "IntakeNode", "scope": "outer",
 "duration_s": 0.01933029099018313}

// node_error  (when a node raises before completion)
{"ts": ..., "type": "node_error",
 "stage": "research", "node": "BibliographyNode", "scope": "subgraph",
 "error": "...", "error_code": "TRC001"}    // error_code added in §6.8.T1

// pipeline_complete
{"ts": ..., "type": "pipeline_complete",
 "run_id": "run-0501-1225_200b",
 "duration_s": 5832.4}

// pipeline_error
{"ts": 1778013702.692657, "type": "pipeline_error",
 "error": "agent.run exceeded 480.0s wall-clock budget"}

// heartbeat  (emitted by L3 daemon thread; see §6.6)
{"ts": ..., "type": "heartbeat", "pid": 12345, "pgid": 12340}

// watchdog_killing  (emitted by L4 watchdog when it sends SIGTERM)
// VERIFIED at output/run-0504-1802_ec44/events.jsonl ralph-27
{"ts": 1777943228.153038, "type": "watchdog_killing",
 "scope": "watchdog", "pgid": 95531, "age_s": 76.6, "strike": 1}

// watchdog_killed  (emitted after SIGTERM/SIGKILL completes)
// VERIFIED at output/run-0504-1802_ec44/events.jsonl ralph-27
{"ts": 1777943229.159349, "type": "watchdog_killed",
 "scope": "watchdog", "killed_cleanly": true}

// watchdog_resuming  (emitted before invoking make resume)
// VERIFIED at output/run-0504-1802_ec44/events.jsonl ralph-27
{"ts": 1777943229.1627991, "type": "watchdog_resuming",
 "scope": "watchdog"}

// watchdog_resumed  (emitted after make resume successfully spawns)
// VERIFIED in dashboard whitelist at runtime/dashboard.py:215 ralph-28
// (not seen in current production samples but supported by renderer)
{"ts": ..., "type": "watchdog_resumed", "scope": "watchdog"}

// watchdog_aborted  (emitted on 3-strikes abort path)
// VERIFIED in dashboard whitelist at runtime/dashboard.py:216 ralph-28
// Sets PipelineState.pipeline_status="watchdog_aborted"; carries
// `reason` field used by dashboard error panel (dashboard.py:237)
{"ts": ..., "type": "watchdog_aborted", "scope": "watchdog",
 "reason": "watchdog 3-strikes abort"}
```

**Complete watchdog event-type set (5 types):** `watchdog_killing`, `watchdog_killed`, `watchdog_resuming`, `watchdog_resumed`, `watchdog_aborted`. All 5 in the dashboard `apply_event` whitelist at `runtime/dashboard.py:213-216` (verified ralph-28). Loop must emit ALL of these correctly when implementing §6.6.T2 — the dashboard already handles them.

**Verified `pipeline_status` enum** (per `runtime/dashboard.py:83`): `"pending" | "running" | "completed" | "error" | "watchdog_aborted"`. The watchdog_aborted status is the terminal sink for the 3-strikes abort path. Add as the 5th value to any consumer code that switches on status.

### 18.6.1 Architectural trap — `IssueSeverity` collision

**Two different `IssueSeverity` types exist in the codebase, with different cases and different values.** The loop must NOT confuse them; verified ralph-47:

| Source | Type | Values | Used by |
|---|---|---|---|
| `core/enums.py:95` | `StrEnum` | lowercase: `critical`, `major`, `minor`, `suggestion` (4 values) | EIC + DA review issues; `SEVERITY_RANK` dict at `enums.py:104` ranks them |
| `models/shared.py:83` | `Literal` | uppercase: `SERIOUS`, `MEDIUM`, `MINOR` (3 values) | Integrity report issues |

When importing, be explicit: `from academic_pipeline.core.enums import IssueSeverity` (review side) vs `from academic_pipeline.models.shared import IssueSeverity` (integrity side). The Pyright type-checker will catch most confusions but reading code that uses bare `IssueSeverity` requires checking the import line.

### 18.6 Verified enum values (loop must use these literal strings)

The PRD elsewhere has used some of these in lowercase / different word forms colloquially. The events.jsonl, dashboard, and any consumer code must use the literal `.value` from the enum class. **Verified against `src/academic_pipeline/core/enums.py` at HEAD:**

| Enum | Source | Values (literal) | Common drift |
|---|---|---|---|
| `Stage` | `core/enums.py:8` | `"research"`, **`"write"`** (NOT `"writing"`), `"experiment"`, `"pre_integrity"`, `"review"`, `"final_integrity"`, `"finalize"`, `"summary"` | PRD prose uses `"writing"` (subgraph folder name) but Stage value is `"write"`. Production events.jsonl confirms: `stage: "write"` (verified ralph-29 from real samples). |
| `PipelineStatus` | `core/enums.py:21` | `"initializing"`, `"running"`, `"awaiting_confirmation"`, `"paused"`, `"completed"`, `"aborted"` (6 values) | Distinct from dashboard's 5-value `pipeline_status` field — see "Two status concepts" below |
| `StageStatus` | `core/enums.py:32` | `"pending"`, `"in_progress"`, `"completed"`, `"skipped"`, `"blocked"` | per-stage status tracker, separate from PipelineStatus |
| `Verdict` | `core/enums.py:59` | `"PASS"`, **`"PASS_WITH_CONDITIONS"`** (NOT `"PASS_WITH_NOTES"`), `"REVISE"`, `"FAIL"`, `"BLOCKED"`, `"CLEARED"` (6 values) | PRD initially used PASS_WITH_NOTES — fixed in §6.1 contract |
| `EditorialDecision` | `core/enums.py:70` | **`"Accept"`** (Title Case), **`"Minor Revision"`** (Title Case + space), **`"Major Revision"`**, **`"Reject"`** | PRD prose says "accept | revise | reject" lowercase; actual literals are Title Case with internal spaces. `EditorialDecision.from_label()` exists for case-insensitive parsing |
| `ReviewDimension` | `core/enums.py:85` | `"originality"`, `"methodology"`, `"evidence"`, `"coherence"`, `"writing"` (5 dimensions) | scored by EIC and referenced by DA issues |
| `IssueSeverity` (StrEnum, **review side**) | `core/enums.py:95` | `"critical"`, `"major"`, `"minor"`, `"suggestion"` (4, in rank order) | `SEVERITY_RANK` dict at `core/enums.py:104` maps to int |
| `IssueSeverity` (Literal, **integrity side**) | `models/shared.py:83` | `"SERIOUS"`, `"MEDIUM"`, `"MINOR"` (3, **uppercase**) | Integrity report issues — DO NOT confuse with the review-side enum |
| `IntegrityVerdict` (Literal) | `models/shared.py:84` | `"PASS"`, `"PASS_WITH_CONDITIONS"`, `"FAIL"` (3) — **5th verdict-like type** in the codebase per the inventory in §6.11 (verdicts: `Verdict` enum 6 values, `StageVerdict` 4, `ClaimVerdict` 3, `EvaluationResult.verdict` 2, `IntegrityVerdict` 3) | Integrity report final verdict |
| `StructureType` (Literal) | `models/shared.py:63` | `"IMRaD"`, `"literature_review"`, `"theoretical"`, `"case_study"`, `"policy_brief"`, `"conference"` (6, NOT just IMRaD vs sysrev as PRD §6.3 prose said) | `PaperDraft.structure_type` default `"IMRaD"`; the §6.15 `imrad_completeness` judge only fires for `"IMRaD"` papers, other structure types have different completeness rubrics |
| `CitationFormat` (Literal) | `models/shared.py:62` | `"APA7"`, `"Chicago"`, `"MLA"`, `"IEEE"`, `"Vancouver"` (5, matches `tools/bibliography/citations.py::STYLE_DISPATCH` per ralph-30) | `PaperDraft.citation_format` default `"APA7"` |
| `ArgumentStrength` (Literal) | `models/shared.py:71` | `"compelling"`, `"strong"`, `"adequate"`, `"weak"` (4) | `Section.argument_strength` |
| `ModifierStyle` (Literal) | `models/shared.py:72` | `"minimal"`, `"moderate"`, `"elaborate"` (3) | StyleProfile + writing-style metrics |
| `WeaknessType` (Literal) | `models/shared.py:75` | `"methodology"`, `"theory"`, `"evidence"`, `"writing"`, `"structure"`, `"ethics"` (6) | review weaknesses (peer reviewer + DA) |
| `WeaknessSeverity` (Literal) | `models/shared.py:76` | `"critical"`, `"major"`, `"minor"` (3, lowercase) | review weaknesses — distinct from review-side `IssueSeverity` enum |
| `ConsensusLevel` (Literal) | `models/shared.py:77` | `"CONSENSUS-4"`, `"CONSENSUS-3"`, `"SPLIT"`, `"DA-CRITICAL"` (4) | reviewer panel consensus |
| `ItemType` (Literal) | `models/shared.py:78` | `"Major"`, `"Minor"`, `"Editorial"` (3, Title-Case) | Revision item types |
| `Priority` (Literal) | `models/shared.py:79` | `"must_fix"`, `"should_fix"`, `"consider"` (3) | Revision priority |
| `ResponseStatus` (Literal) | `models/shared.py:80` | `"RESOLVED"`, `"DELIBERATE_LIMITATION"`, `"UNRESOLVABLE"`, `"REVIEWER_DISAGREE"` (4) | Author response to reviewers |
| `RevisionSource` | `core/enums.py:107` | `"editor_in_chief"` (only value at HEAD) | extensible enum |
| `AgentType` | `core/enums.py:50` | `"research"`, `"writing"`, `"review"`, `"integrity"` (4 values) | for routing/logging — note: `"writing"` here, not `"write"` (different from Stage!) |
| `CheckpointType` | `core/enums.py:42` | `"FULL"`, `"SLIM"`, `"MANDATORY"` (uppercase!) | only enum with all-caps values |

### Three status concepts (do not conflate) — verified ralph-61

The codebase has THREE different status fields that look similar but are NOT the same:

| Concept | Location | Values | Used by |
|---|---|---|---|
| `PipelineStatus` enum | `core/enums.py:21`, stored on `PipelineState.pipeline_status` | 6 values: `initializing`, `running`, `awaiting_confirmation`, `paused`, `completed`, `aborted` | core orchestration; pipeline-graph status |
| `RunState.pipeline_status` field | `runtime/dashboard.py:83` (string literal) | 5 values: `"pending"`, `"running"`, `"completed"`, `"error"`, `"watchdog_aborted"` | dashboard rendering only |
| `StageInfo.status` field | `runtime/dashboard.py:59` (string literal) | 4 values: `"pending"`, `"running"`, `"completed"`, `"error"` | per-stage rendering within dashboard |

The dashboard's `"watchdog_aborted"` is NOT the same as `PipelineStatus.ABORTED.value = "aborted"`. The dashboard's `StageInfo.status` lacks the `"watchdog_aborted"` value (it's per-stage, not run-level). Loop must use the right one for the right context. Recommended: rename one of them in a future cleanup, but for v2.5.0 leave as-is + document (this entry).

### Stage value vs subgraph folder name (do not conflate)

| Subgraph folder | Stage enum value | AgentType value |
|---|---|---|
| `src/academic_pipeline/research/` | `Stage.RESEARCH = "research"` | `AgentType.RESEARCH = "research"` |
| `src/academic_pipeline/writing/` | **`Stage.WRITE = "write"`** | **`AgentType.WRITING = "writing"`** |
| `src/academic_pipeline/experiment/` | `Stage.EXPERIMENT = "experiment"` | (no entry) |
| `src/academic_pipeline/review/` | `Stage.REVIEW = "review"` | `AgentType.REVIEW = "review"` |
| `src/academic_pipeline/integrity/` | `Stage.PRE_INTEGRITY = "pre_integrity"` + `Stage.FINAL_INTEGRITY = "final_integrity"` | `AgentType.INTEGRITY = "integrity"` |

The writing folder vs Stage vs AgentType triplet is the trap: **folder = `writing/`, Stage value = `"write"`, AgentType value = `"writing"`**. Three different strings for the same concept across three different layers.

**Caveat for §6.6.T2 generic `recovery_event`:** the 3 `watchdog_*` event types already exist at HEAD (verified 2026-05-06 from production samples). §6.6.T2 introduces a new `recovery_event` type with `layer`/`action`/`reason` fields. Two design options for v2.5.0: (a) keep the 3 specific types AND add the new generic — duplication but backward-compat; (b) deprecate the 3 specific in favor of the generic — cleaner schema but breaks any consumer (Logfire saved searches, custom scripts) that grep for `watchdog_killing`. **Recommendation: (a) — keep both.** The new `recovery_event` adds layers 1–3 (transport, bounded_run, heartbeat) which currently emit no events; the 3 `watchdog_*` cover only L4 with richer per-action shape. Document the relationship in `docs/architecture/recovery.md` (§6.6.T3).

#### New event types added in v2.5.0

##### `recovery_event` (§6.6.T2 / §6.13.T1)
```json
{"ts": ..., "type": "recovery_event",
 "layer": 4,                    // 1..4 — which recovery layer fired
 "action": "kill",              // "kill" | "resume" | "abort"
 "reason": "events_jsonl stale 612s ≥ 600s",
 "strike": 1,                   // 1..3
 "error_code": "REC004"}
```

##### `doi_gate_failure` (§6.7.T2)
```json
{"ts": ..., "type": "doi_gate_failure",
 "doi": "10.1234/example.bad",
 "crossref_status": 404,
 "blocking": true,              // false if --allow-unverified-dois
 "error_code": "REN001"}
```

##### `cascade_verdict` (§6.4)
```json
{"ts": ..., "type": "cascade_verdict",
 "stage": "A",                  // "A" | "B" | "C"
 "verdict": "fail",             // "pass" | "fail"
 "score": 0.42,
 "reason": "3 numeric claims lack trace tokens",
 "short_circuited": true,
 "error_code": "CAS001"}        // omitted when verdict=="pass"
```

##### `novelty_gate_verdict` (§6.1, Spec 3)

Verified ralph-36: actual `NoveltyVerdict` enum at `models/novelty_gate.py` has 3 values `"novel"` / `"partial"` / `"redundant"` (NOT `"soft_warn"` as earlier PRD said). Decision tree per `research/novelty_gate.py:138-146`: `max_sim < τ_warn` → NOVEL; `τ_warn ≤ max_sim < τ_block` → PARTIAL; `max_sim ≥ τ_block` → REDUNDANT.

```json
{"ts": ..., "type": "novelty_gate_verdict",
 "verdict": "partial",          // "novel" | "partial" | "redundant"
 "max_similarity": 0.83,
 "tau_warn": 0.78, "tau_block": 0.92,
 "neighbors": [{"title": "...", "doi": "...",
                "semantic_scholar_id": "...",
                "cosine_similarity": 0.83,
                "abstract_excerpt": "first 200 chars..."}, ...],
 "differentiation_paragraph": "...",  // only set when verdict=="partial" per Spec 3 design
 "error_code": "NOV003"}        // omitted when verdict=="novel"
```

##### `ethics_checklist_result` (§6.5, Spec 8)
```json
{"ts": ..., "type": "ethics_checklist_result",
 "items_total": 12,
 "items_pass": 10, "items_fail": 1, "items_na": 1,
 "fails": [{"item": "data_provenance_disclosed", "reason": "..."}],
 "blocking": true,
 "error_code": "ETH004"}        // omitted when items_fail==0
```

##### `design_bundle_scores` (§6.2, Spec 7)
```json
{"ts": ..., "type": "design_bundle_scores",
 "n_designs": 4, "k_run": 2,
 "scores": [{"design_id": "d1", "score": 8.7}, ...],
 "selected": ["d1", "d3"]}
```

##### `judge_alignment` (§6.15, weekly re-alignment per T12)
```json
{"ts": ..., "type": "judge_alignment",
 "judge": "thesis_coherence",
 "tpr": 0.88, "tnr": 0.91,
 "split": "test", "n": 75,
 "warning": false,              // true if either drops below 0.85
 "error_code": "EVL002"}        // omitted when warning==false
```

##### `regression_result` (§6.15.T9, fired by `make test-regression`)
```json
{"ts": ..., "type": "regression_result",
 "phase": "B",                  // "A" | "B" | "C"
 "fixture": "medical_imaging_clf",
 "judge": "fabricated_numeric",
 "pass": true,
 "ci_lower": 0.74,
 "error_code": "EVL003"}        // omitted when pass==true
```

### 18.3 Forward compatibility

- Consumers MUST tolerate **unknown event types** (skip with a warning, do not crash). New types are additive.
- Consumers MUST tolerate **unknown extra fields** on known event types (ignore). Producers may add new fields to existing types in minor versions.
- Producers MUST NOT change the type or removeessful fields on existing event types in minor versions. Such changes require major version bump (schema version `3.x.x`).
- The `version` first-line marker MUST agree with `pyproject.toml::version` at minor granularity.

### 18.4 Multi-record-per-event invariant

Some events trigger BOTH an events.jsonl record AND a Logfire span (§6.13). Both must carry the same `error_code` and `ts` (within ±1 second). The Logfire span name SHOULD be the event type string (e.g., `cascade_verdict`).

### 18.5 Append-only invariant

The file is opened with `mode="a"`, written with `f.flush() + os.fsync()` per record (verified in `runtime/events.py::EventLogger.emit_sync`). Consumers MUST tolerate a malformed final line (mid-write crash). Use `try/except json.JSONDecodeError: continue` on the last line only.

---

## 19. Regression Vectors

For every Phase 2 wiring that changes default behavior, this section lists what existing behavior could break and how to mitigate. The loop must consult this section before flipping any flag default and surface any unmitigated regressions to Jackson before merging.

**Severity rubric:**
- 🔴 **Hard break** — pre-v2.5.0 artifact / state / behavior unusable. Migration script or `legacy_*` flag required.
- 🟡 **Behavior shift** — pipeline still runs; output characteristics change in ways users will notice.
- 🟢 **Performance shift** — same output, different cost/latency profile. Document but no migration needed.

| # | Component | Phase 2 change | Severity | Blast radius | Mitigation |
|---|---|---|---|---|---|
| R1 | §6.1 | `chain_of_ideas_enabled` flips on, `KnowledgeGraphNode` deleted | 🔴 | Any pre-v2.5.0 state file with `state.knowledge_graph` populated; any external tool reading `models/research.py::KnowledgeGraph` | `legacy_knowledge_graph` flag (defaults false) restores; cleanup script (§6.9.T5) on state files; CHANGELOG entry under "Renamed (BREAKING)" pattern from v2.4.0 |
| R2 | §6.1 | `novelty_gate_enabled` flips on with hard-block at `tau_block=0.92` | 🟡 | Topics that v2.4.0 happily worked may now be aborted at intake | Tune `novelty_gate_tau_block` upward case-by-case; document override path in `docs/architecture/novelty.md` (new); verification: `make test-regression` Phase A asserts no fixture topic is hard-blocked |
| R3 | §6.1 | Ethics removed from research → moved to integrity (§6.5) | 🔴 | State files mid-research-phase reference deleted `EthicsReviewNode` | State schema version bump (§6.9.T1) + `IncompatibleStateError` at resume; cleanup script. **Must land §6.1.T6 + §6.5.T1 in same release tag** — never an interim where neither exists |
| R4 | §6.2 | `InteractiveMLNode` + `JudgeNode` classes deleted | 🔴 | Pre-cutover state files raise `AttributeError` on snapshot deserialization | Already documented in CLAUDE.md ("Pre-cutover runs cannot resume"); cleanup script removes stale state files; CHANGELOG documents |
| R5 | §6.2 | `docker/experiment/tcp_server.py` removed + Dockerfile entry | 🔴 | Any in-flight experiment workspace from before cutover that started the TCP server | Documented in §6.2.T7; in-flight runs must be killed before upgrade |
| R6 | §6.2 | Stages 3–6 added (classification/regression, timeseries, multimodal, DVC) | 🟡 | `config_writer` agent prompt may not yet emit valid configs for new `problem.type` values | §6.2.T1–T4 each include a `config_writer` prompt update; verification: 3 of 5 fixture topics in §6.15 exercise new stages |
| R7 | §6.2 | `exploration_breadth_enabled` flips on; K parallel Dagster runs | 🟢🟡 | API spend multiplied by K (default 2); rate limits more likely to fire; `AnalysisNode` returns `list[ExperimentResults]` instead of single | Per-account rate limit budget review; `legacy_single_design` escape hatch; `AnalysisNode` consumers (`DraftWriter`, `SectionWriter`) must accept both single + list — type annotation enforces; verification: §6.15 fixture topics include both modes |
| R8 | §6.3 | `traceability_mode: full` default | 🟡 | Unresolved trace tokens in section bodies now fail editorial → +1 revision cycle per affected section; total run time may increase 10–20% | Phase 1 partial mode covered ~85% of patterns; remaining 15% surface as TRC errors and are debuggable. `legacy_traceability_off` flag for emergency revert |
| R9 | §6.3 | `--template {ieee,acl}` flag added; ACL path supported | 🟢 | New code path for ACL; CI must cover ACL template (§6.7.T6 + §6.14.T1 medium tests) | Default remains `ieee`; ACL must be opt-in per-run until proven |
| R10 | §6.3 | StructureArchitect requires `thesis_advancing_role` per section; Pre-Integrity rejects empty | 🟡 | Any cached writing snapshot from v2.4.0 lacks the field → re-run from StructureArchitect on resume | State schema version bump catches this; CHANGELOG documents; affected resumes restart from StructureArchitect (existing resume mechanic) |
| R11 | §6.4 | Persona reviewers default; legacy 3 reviewers behind `legacy_reviewers` flag | 🟡 | Different review depth + different "pet peeves" → different revision directives → different Writing iterations | Compare-and-contrast happens in §6.15.T10 spot-review (one paper is v2.4.0/v2.5.0 side-by-side); rollback via `legacy_reviewers=true` |
| R12 | §6.4 | `EditorialSynthesizerNode` enforces `CascadeResult` verdict (cannot override) | 🟡 | Borderline papers that v2.4.0 editorial would soft-pass now hard-reject when cascade Stage A or B fails | `cascade_short_circuit_on_stage_c=false` (default) keeps Stage C as soft. Stages A and B short-circuit hard — by design. If too aggressive, raise rubric thresholds rather than disabling cascade |
| R13 | §6.4 | Cascade Stage A consumes trace tokens directly | 🔴 (interaction) | A topic with no experiment subgraph may have zero trace tokens → Stage A trivially passes (vacuously) OR fails (no tokens to validate) — depends on implementation | Implementation must distinguish "no claims to validate" (PASS-vacuous) from "claims present but not tokenized" (FAIL). Specify in §6.4.T4 acceptance test |
| R14 | §6.5 | `EthicsChecklistNode` replaces freeform `EthicsReviewNode`; default on | 🟡 | Stricter checklist surfaces issues that freeform happily skipped → more papers loop back through integrity-fix | `max_integrity_fix_loops: 3` already caps. Items can be marked `n/a` with override directive. CHANGELOG warns users |
| R15 | §6.6 | New `recovery_event` records in events.jsonl | 🟡 | Pre-§6.8.T1 dashboard renderers don't know the type → may crash | Schema version marker (§6.8.T3) + DSH004 UnknownEventType warning. Per §18.3, consumers MUST tolerate. v2.4.0 dashboard.py needs update — bundled with v2.5.0 release |
| R16 | §6.6 | `--max-recoveries` flag added (default 3 unchanged) | 🟢 | Behavior unchanged at default; users can now override | Document in `docs/architecture/recovery.md` |
| R17 | §6.7 | DOI CrossRef build gate, default strict | 🔴 | Builds that previously compiled with unverified DOIs now fail with REN001 | `--allow-unverified-dois` escape hatch; documented in `docs/architecture/rendering.md`; pre-existing bibtex files may need DOI cleanup |
| R18 | §6.7 | `authors.yaml` required at compile time | 🔴 | Existing run dirs without `authors.yaml` cannot re-render | Templated `authors.yaml` auto-created by intake when missing; existing dirs need manual creation; cleanup script can offer to seed |
| R19 | §6.7 | Title 12-word constraint at formatter | 🟡 | Topics that produce titles > 12 words need one revision attempt; if still too long, formatter fails | `formatter` `output_validator` allows one retry; if still too long, REN003 raises and writing loops back |
| R20 | §6.7 | `scripts/rerender_latest.py` deleted | 🔴 | Any documentation, Makefile target, or workflow referencing it breaks | Grep before delete (§15 cross-cutting deletions audit); replace with thin wrapper or document path forward |
| R21 | §6.8 | Schema version marker as first line | 🔴 | Pre-v2.5.0 events.jsonl lacks the marker; renderer rejects | DSH001 SchemaVersionMismatch error tells user to upgrade renderer; older events.jsonl files must be tagged manually if reading post-upgrade |
| R22 | §6.9 | State schema version bump | 🔴 | All pre-v2.5.0 `.pipeline_runs/*.json` raise PRS001 IncompatibleStateError on resume | `tools/cleanup_state.py --before 2.5.0 --confirm` deletes them; CHANGELOG warns users to run `make resume` on in-flight runs before upgrading |
| R23 | §6.9 | Per-agent cache files (was single-file) | 🔴 | Old single-file `_agent_cache.json` not loaded by new factory | Migration: cleanup script also handles old cache files; in-flight ML engineer dialogues lost (acceptable — judge loops are short-lived) |
| R24 | §6.10 | Substitution layer hard-fails on unresolved tokens (was warn) | 🟡 | Phase 1 papers had warnings; v2.5.0 papers get TRC003 SubstitutionFailure → revision cycle | Existing warnings are real bugs being elevated to errors — fixing them is the point. `legacy_traceability_off` for emergency |
| R25 | §6.10 | Per-agent ContextSpec migrations | 🟡 | Each migrated agent receives slightly different context payload → subtle prompt-behavior shifts | One agent at a time; verify each via tests/unit/<subgraph>/ before next |
| R26 | §6.11 | Hedge-language hard-veto patterns extended | 🟡 | Existing acceptable hedge phrasings ("we note" / "preliminary") may now veto | Patterns explicit in `_patterns.py`; tunable per-deployment; QGT003 raises with the offending phrase for adjustment |
| R27 | §6.11 | Per-node `node_quality_thresholds` map | 🟢 | Default 7.0 still applies for unmapped nodes; raised thresholds → more local iterations on those nodes | Cost rises proportionally for high-threshold nodes; tune via `configs/dev.yaml` per deployment |
| R28 | §6.12 | Version unification (`VERSION`/`pyproject.toml`/badges all → 2.5.0) | 🟡 | Tests asserting `__version__ == "0.2.0"` fail; doc snippets with hardcoded versions stale | Grep for hardcoded version strings before bump; CIR001 PyprojectVersionDrift catches future regressions |
| R29 | §6.12 | `fastapi` + `uvicorn` extras removed (pending T7 audit) | 🔴 | Any code that imported them silently fails | Grep `from fastapi` / `from uvicorn` first; if any usage exists, document the consumer instead of removing |
| R30 | §6.13 | New Logfire span attributes for cascade/novelty/ethics events | 🟢 | Existing Logfire saved-searches/dashboards lack the new attribute names | Documented in `docs/architecture/observability.md`; Logfire ignores unknown filters gracefully |
| R31 | §6.14 | New required CI jobs (test-medium, version-consistency, pre-commit) | 🟡 | PRs that previously merged are now blocked on the new jobs | Land jobs in monitor-only mode for 1 week, then require; document in `docs/architecture/release.md` |
| R32 | §6.14 | `publish.yml` audited (likely rewritten) | 🔴 | Tag-triggered behavior may differ from current (unaudited) — possibly publishes/doesn't-publish to PyPI; possibly creates GitHub Release | §6.14.T2 audits FIRST before any v2.5.0-rc tag; documented behavior locked into `docs/architecture/release.md` |
| R33 | §6.15 | New `make test-regression` step before tag | 🟢 | Release cycle gains 1-week verification phase | Documented in §11; calendar already adjusted to 9–12 weeks |
| R34 | §6.15 | Spot-review checkpoint (Jackson signs 3 papers) | 🟡 (process) | Tag cannot be pushed without manual signoff | By design — this IS the gate. Ralph loop must HALT at the spot-review stage and surface to Jackson |

### Loop directive for regressions

Before flipping a flag default or merging a Phase 2 wiring, the loop MUST:
1. Look up the corresponding R-row in this table.
2. Confirm the listed mitigation is in place (script written, flag added, doc updated, etc.).
3. If a regression has no listed mitigation, surface it to Jackson and HALT — do not merge.
4. After the wiring lands and tests pass, **also run the in-flight uncommitted resume scenario** (`make run` on a fixture, kill mid-run, `make resume`) to catch any unexpected interaction. Surface results to Jackson.

A 🔴 regression without a verified mitigation is grounds to revert the entire Phase 2 wiring — partial breakage is worse than legacy behavior.

---

## 20. Migration Scripts Inventory

Every 🔴 regression in §19 needs a migration path. Some are one-shot scripts a user runs once before/after the v2.5.0 upgrade; others are CI-runnable invariant checks. This section is the authoritative inventory.

| Script | Purpose | Closes regressions | Lives at | Reads | Writes / Deletes | Idempotent? | Safe to re-run? |
|---|---|---|---|---|---|---|---|
| `tools/check_version_consistency.py` | CI-runnable invariant: `VERSION` file == `pyproject.toml::version` == README badge `v…` | R28 (CIR001) | new file at repo `tools/` | `VERSION`, `pyproject.toml`, `README.md` | exit 0/1 only | yes | yes |
| `tools/cleanup_state.py` | Walk `.pipeline_runs/` and delete state files older than the schema version cutoff. Also archives the deleted files to `.pipeline_runs/_archive/` first (not `rm`) so user can recover if mistaken. | R3, R4, R10, R22, R23 (PRS001) | new file at repo `tools/` | `.pipeline_runs/*.json`, `.pipeline_runs/*_agent_cache.json` | moves to `.pipeline_runs/_archive/<timestamp>/` | yes (no-op on already-cleaned dir) | yes |
| `tools/migrate_authors_yaml.py` | For each `output/<run-id>/` dir lacking `authors.yaml`, seed from `templates/authors.default.yaml` (new) and prompt user to fill in. | R18 (REN002) | new file at repo `tools/` | `output/*/manuscript.tex` (to detect render attempts), absence of `output/*/authors.yaml` | creates `output/<run-id>/authors.yaml` from template | yes | yes |
| `tools/grep_orphan_imports.py` | Pre-deletion check: greps `src/` and `tests/` for any import of the named module/symbol. Prints results, exits 1 if found. | R20 (`scripts/rerender_latest.py`), R29 (`fastapi`/`uvicorn`/`figure_executor`) | new file at repo `tools/` | `src/`, `tests/`, `examples/`, `scripts/` | exit 0/1 + stderr report | yes | yes |
| `tools/audit_publish_yml.py` | One-shot script (run by §6.14.T2 audit task) that parses `.github/workflows/publish.yml`, prints triggers + secrets used + target registries, and writes findings to `docs/architecture/release.md`. | R32 (CIR002) | new file at repo `tools/` | `.github/workflows/publish.yml` | appends to `docs/architecture/release.md` | yes | yes — but only useful pre-rewrite |
| `tools/migrate_agent_cache.py` | For old single-file `_agent_cache.json` under `.pipeline_runs/`, split into per-agent files matching new `for_agent(agent_name, thread_id)` factory. | R23 (PRS003) | new file at repo `tools/` | `.pipeline_runs/<thread_id>_agent_cache.json` | creates `.pipeline_runs/<thread_id>_<agent>_cache.json` per agent; archives original | yes | yes |
| `tools/dagster_workspace_cleanup.py` | For each `output/<run-id>/02-experiment/` dir, check if it predates the Dagster cutover (presence of monolithic `experiment.py` + `_state.pkl`). Mark as legacy; offer to archive. | R5 (in-flight pre-cutover workspaces) | new file at repo `tools/` | `output/<run-id>/02-experiment/` contents | moves legacy dirs to `output/_legacy_pre_dagster/<run-id>/` | yes | yes |

### Migration runbook

When a user upgrades from v2.4.0 → v2.5.0, the order MUST be:

```bash
# Step 1: Pre-flight — make sure nothing is mid-flight
make list-runs
# manually decide whether to resume each, or accept that they'll be archived

# Step 2: Pull v2.5.0
git fetch origin
git checkout v2.5.0
uv sync --all-extras

# Step 3: Version sanity
uv run python tools/check_version_consistency.py

# Step 4: Clean up incompatible state files (interactive — confirms each)
uv run python tools/cleanup_state.py --before 2.5.0
# When prompted, type "yes" to archive

# Step 5: Migrate agent caches (incremental — same pattern)
uv run python tools/migrate_agent_cache.py --before 2.5.0

# Step 6: Seed missing authors.yaml on existing run dirs (only if you intend to re-render)
uv run python tools/migrate_authors_yaml.py

# Step 7: Quarantine pre-Dagster experiment workspaces
uv run python tools/dagster_workspace_cleanup.py

# Step 8: Verify with the regression suite
make test-regression

# Step 9: Try a fresh run
make run TOPIC="<sample>" --thread-id _v25_smoke
```

If any step fails, the script archives rather than deletes, so rollback is `git checkout v2.4.0 && uv sync && cp .pipeline_runs/_archive/<ts>/* .pipeline_runs/`.

### Migration runbook lives at `docs/architecture/migrations.md`

§6.12.T9 must include adding `migrations.md` to the docs index. The runbook above is the seed content.

### CI integration

- `tools/check_version_consistency.py` is invoked from `make check` and from `.github/workflows/ci.yml::version-consistency` job (§6.14.T3).
- `tools/grep_orphan_imports.py` is invoked manually before deletions, NOT in CI (would block all PRs that delete unused code paths).
- All other scripts are user-invoked one-shots, not CI-gated.

### Loop directive

Before deleting a file (R5, R20, R29) or bumping a state schema (R22, R23), the loop MUST:
1. Run `tools/grep_orphan_imports.py --module <to-be-deleted>` — confirm no orphan callers.
2. Verify the corresponding migration script exists and has a unit test in `tests/unit/tools/test_migrations.py`.
3. Verify the migration script archives (not deletes) by default — only `--purge` flag actually deletes.
4. Update `docs/architecture/migrations.md` with the new step in the runbook.

Skipping any of these steps puts user data at risk and is grounds to revert.

---

## 21. Failure Mode Traceability Matrix

The 6 failure modes locked in §6.15.T4b each have:
- **Preventers**: components whose Phase 2 wiring is supposed to make this failure mode rare
- **Detector**: the §6.15 judge that scores whether the failure occurred
- **Hard-gate**: any §17 error code that aborts the pipeline if detected upstream

When a failure surfaces in production (judge fires, post-run review, or peer reviewer flags), trace through this matrix:

| Failure mode (§6.15.T4b) | Preventers (Phase 2 wirings) | Detector (LLM-as-Judge) | Hard-gate error code | Anti-pattern that causes it |
|---|---|---|---|---|
| **hedge_language_in_results** — Results sections use phrases like "interim", "subject to revision", "full search awaits" instead of stating findings | §6.11.T2 (hard-veto patterns), §6.10 (trace tokens force numeric grounding), §6.4 cascade Stage A (numerical claim audit) | `evaluation/judges/specs/hedge_language.yaml` (FBR001) | QGT003 HedgeLanguageDetected | SectionWriter generating placeholder text when synthesis is incomplete instead of flagging `[MATERIAL GAP]` |
| **thesis_incoherence** — Manuscript reads as a literature review or summary; no clear arc; sections don't advance a thesis | §6.1 (ChainOfIdeasExtractor + ThesisExtractor produce DevelopmentChain + ThesisStatement); §6.3.T3 (StructureArchitect requires `thesis_advancing_role` per section); §6.3.T4 (Pre-Integrity rejects empty roles) | `evaluation/judges/specs/thesis_coherence.yaml` (FBR002) | COI002 ThesisAbsent | KnowledgeGraphNode using bib refs as nodes (the v2.4.0 weakness — `feedback_knowledge_graph_weakness`) |
| **persona_tone_mismatch** — Writing tone doesn't match target journal/audience (overly casual for SCI, overly formal for workshop, etc.) | §6.3 (intake captures audience; section_writer + draft_writer prompts include persona); §6.4 (persona reviewer panel — Spec 5 — different reviewers catch different tone mismatches) | `evaluation/judges/specs/persona_tone_mismatch.yaml` (FBR003) | PRR001 PersonaUnknown | Single generic "academic" persona prompt instead of journal-specific (`target_journal` config field exists but unused in v2.4.0 prompts) |
| **citation_orphan** — Paragraph contains claims but zero citations and zero trace tokens | §6.7 (citation_resolver pre-flight on rendered sections); §6.10.T4 (substitution validator hard-fails on unresolved tokens); §6.4 cascade Stage A (numerical claims must be cited or tokenized) | `evaluation/judges/specs/citation_orphan.yaml` (FBR004) | TRC003 SubstitutionFailure | DraftWriter producing summary paragraphs from internal model knowledge instead of from the bibliography |
| **fabricated_numeric** — Numeric value (percentage, AUROC, p-value) appears in body but is not derivable from `ExperimentResults` or a verified source | §6.10 (trace tokens + substitution); §6.4 cascade Stage A (numerical claim audit); §6.11.T2 (missing-trace-token veto); §6.7 (DOI gate catches fabricated citations of numbers) | `evaluation/judges/specs/fabricated_numeric.yaml` (FBR005) | TRC001 NumericValidatorRetry, TRC002 NumericValidatorAbort, QGT004 MissingTraceTokenInClaim, CAS001 StageANumericFail | SectionWriter inventing pooled estimates, heterogeneity stats, or figure callouts when synthesis defers (the v2.4.0 weakness — `feedback_writing_fabricates_numbers`) |
| **imrad_incompleteness** — Paper expected to be IMRaD (because experiment present) but missing Methods, Results, or Discussion section | §6.3 (StructureArchitect IMRaD switch when `ExperimentResults` is non-empty); §6.7 (formatter validates required sections per template) | `evaluation/judges/specs/imrad_completeness.yaml` (FBR006) + structural assertion in `tools/output_assertions.py` | REN004 TectonicCompileFail (downstream symptom) | StructureArchitect producing systematic-review structure even when experiment data is present |

### Bidirectional check

When a Phase 2 wiring lands, verify that the failure modes it claims to prevent become measurably less frequent on the regression suite. When a judge's TPR/TNR drops, trace back to which preventer was weakened.

### How a failure surfaces → action mapping

| Surface | Action |
|---|---|
| Judge fires on a fixture in `make test-regression` Phase A/B | Find row in this matrix → root-cause the failed preventer → file a Phase 2 fix |
| Hard-gate error code raised in production | Find row in this matrix by error code → cross-reference §17 namespace + §19 regression vector |
| Peer reviewer flags an issue not in this matrix | Add a 7th failure mode to §6.15.T4b backlog; do NOT silently expand an existing mode |
| Spot-review (§6.15.T10) catches an issue judges missed | Identify failure mode → check if existing judge prompt is too narrow → refine via §6.15.T6 alignment loop on labeled traces |

### Anti-pattern: silent failure-mode expansion

When a peer reviewer flags an issue that doesn't cleanly map to one of the 6 failure modes, the temptation is to expand an existing mode's definition. **Don't.** Instead:
1. Open a new failure-mode candidate in `docs/evaluation/failure-modes.md` under "Backlog".
2. Label 30+ Pass + 30+ Fail traces for the new mode.
3. Build a new judge per §6.15 chapter 5 methodology.
4. Add a 7th row to the table above.

Expanding an existing mode silently invalidates its TPR/TNR (the labeled trace set was for the original definition).

---

## 22. Test Cadence and Tier Mapping

The test suite is staged across three tiers per Google's pyramid (already established in `pyproject.toml::addopts = "-m 'not medium and not large'"`). v2.5.0 keeps the tier system but adds a fourth release-gate tier and tightens what runs at each cadence.

### 22.1 Tier definitions

| Tier | Marker | Runtime budget | Network? | Docker? | LLM? | Where it runs |
|---|---|---|---|---|---|---|
| **small** (default) | unmarked | each test < 0.5s, suite < 60s | no | no | no (TestModel only) | every PR; `make test`; `make check` |
| **medium** | `@pytest.mark.medium` | each test < 30s, suite < 5 min | yes (mocked) | yes | no (TestModel) | merge to main; `make test-integration`; `.github/workflows/ci.yml::test-medium` (§6.14.T1) |
| **large** | `@pytest.mark.large` | each test < 5 min, suite < 30 min | yes (real APIs) | yes | yes (real Opus 4.7) | manual `make test-e2e`; pre-tag only |
| **regression** (new in v2.5.0) | `@pytest.mark.regression` | per fixture topic ~1–2 hr | yes (real APIs) | yes | yes (real Opus 4.7) | manual `make test-regression`; required pre-tag (§6.15) |

### 22.2 Per-component test count targets (post-v2.5.0)

Approximate. Loop should not optimize against these numbers but use them as sanity check (a component with 0 small tests likely has missing coverage).

| Component | small | medium | large | regression | Total (delta vs v2.4.0) |
|---|---|---|---|---|---|
| §6.1 Research | ~80 (+9 in T9) | ~5 | 1 (research_e2e) | 1 (medical_imaging fixture) | ~87 |
| §6.2 Experiment | ~150 (+13 across T1-T10) | ~12 (+6 across stages 3-6) | 1 (experiment_e2e) | 3 (3 IMRaD fixtures) | ~166 |
| §6.3 Writing | ~75 (+8 in T10) | ~3 (+1 ACL e2e in T6) | — | 5 (covers all fixtures) | ~83 |
| §6.4 Review | ~50 (+6 in T9) | ~3 | — | 5 (covers all fixtures) | ~58 |
| §6.5 Integrity | ~30 (+5 in T5) | ~2 | — | 5 (covers all fixtures) | ~37 |
| §6.6 Recovery | ~40 (existing) | ~6 (+3 in T4) | — | — | ~46 |
| §6.7 Rendering | ~50 (+13 across T1-T7) | ~4 (+1 ACL) | — | 5 (covers all fixtures via PDF assert) | ~59 |
| §6.8 Dashboard + Events | ~25 (+4 in T6) | ~2 (existing) | — | — | ~31 |
| §6.9 Persistence + AgentCache | ~35 (+6 in T6) | ~4 (resume scenarios) | — | — | ~45 |
| §6.10 Traceability | ~55 (+6 in T8) | — | — | 5 (trace tokens in fixtures) | ~61 |
| §6.11 Quality Gate | ~40 (+5 in T6) | — | — | — | ~45 |
| §6.12 Config + SDK | ~30 (+2 skill packs in T8 + 5 examples in T3) | — | — | — | ~37 |
| §6.13 Observability | ~10 (+4 in T5) | — | — | — | ~14 |
| §6.14 CI / Release | ~5 (just `check_version_consistency` + `audit_publish_yml`) | 1 (test-medium meta) | — | — | ~6 |
| §6.15 Output Verification | ~50 (judges, splits, correction, overlap_check) | 6 (per-judge alignment on test split) | — | 5 fixtures × 6 judges = 30 (but counted under each judge once) | ~86 |
| **Sub-total** | **~725** | **~48** | **~2** | **~5** unique fixtures × multiple checks | **~860** |
| Plus tests inherited from v2.4.0 (recovery, persistence, etc., that don't change) | already counted | already counted | — | — | brings total ≥ 1500 per §3.3 gate 2 |

### 22.3 CI job mapping

| Job (in `.github/workflows/ci.yml`) | Tier | Trigger | Required for | Added by |
|---|---|---|---|---|
| `lint` | n/a | every PR | merge | existed |
| `typecheck` | n/a | every PR | merge | existed (**resolve pyright vs basedpyright discrepancy**: `Makefile:98` runs `npx basedpyright`; `pyproject.toml::dev` declares `pyright>=1.1`; `.github/workflows/ci.yml::typecheck` runs `uv run pyright`. Pick one consistently — the TypeScript-first basedpyright is preferred per Makefile evolution; PRs should use `npx basedpyright src/academic_pipeline/`. Add to §6.14 deltas) |
| `test` (3.12 + 3.13 matrix) | small | every PR | merge | existed |
| `pre-commit` | n/a | every PR | merge | §6.14.T4 |
| `version-consistency` | n/a | every PR | merge | §6.14.T3 |
| `test-medium` (CI job; **invokes `make test-integration`** which IS the medium-tier Makefile target — verified Makefile at HEAD: target name is `test-integration`, no separate `test-medium` Make target exists) | medium | merge to main | (informational at first; required after 1-week soak) | §6.14.T1 |
| `test-large` | large | manual / weekly cron | release candidates | not auto-added (cost) |
| `test-regression` | regression | manual / pre-tag | v2.5.0 final tag (§3.3 gate 9) | §6.15.T9 |
| `realign` | regression-adjacent | manual / weekly | (informational; warns if TPR/TNR drops) | §6.15.T12 |

### 22.4 Test fixtures inventory

| Fixture | Lives at | Used by | Refresh cadence |
|---|---|---|---|
| TestModel JSON outputs | `tests/conftest.py::make_test_model` | every small test that touches an agent | as needed when output schemas change |
| Sample bibtex | `tests/fixtures/bibtex/` (existing) | bibliography + citation tests | rarely |
| Sample manuscript markdown | `tests/fixtures/manuscripts/` (existing) | renderer tests | rarely |
| Golden topics + expected outputs | `tests/fixtures/golden/<slug>/` (5 dirs, NEW per §6.15.T1) | regression suite | per major version (locked at v2.5.0 tag) |
| Labeled trace splits | `tests/fixtures/labeled_traces/<failure_mode>/{train,dev,test}.jsonl` (6 modes × 3 splits = 18 files, NEW per §6.15.T4e) | judge alignment + overlap_check | top up via `make realign` weekly (§6.15.T12) |
| Mock Logfire spans | `tests/fixtures/logfire_spans/` (NEW per §6.13.T5) | observability tests | per Logfire schema change |

### 22.5 Loop directive for tests

When the loop adds a delta task implementation:
1. Identify the tier of the verification — small (default), medium (Docker/network), large (real LLM), regression (judge-gated).
2. Mark new tests with the appropriate `@pytest.mark.<tier>` if non-default.
3. Ensure the test runs under the right CI job (cross-check §22.3).
4. If adding regression-tier verification, ensure the corresponding fixture exists in `tests/fixtures/golden/` (§22.4).
5. **Do not silently change a test's tier.** Moving a test from small → medium loses default-CI coverage of that behavior.

### 22.6 Anti-pattern: skipping tier discipline

Tests that "almost pass on real APIs" should be `@pytest.mark.large`, not `@pytest.mark.medium` with a flaky retry. Tests that "want to talk to Docker" should be `@pytest.mark.medium`, not skipped on missing-Docker. The tier system exists to enable parallel CI staging; collapsing it produces "every test is medium" which destroys the per-PR feedback loop.

---

## 23. Definition of Done — v2.5.0 Tag-Day Checklist

Single-page checklist Jackson works through before pushing the v2.5.0 tag. Every box must be checked. Every check links back to the PRD section that owns the underlying work.

### 23.1 Code / process gates (matches §3.3 gates 1–8)

```
[ ] (G1) All 8 SCI Phase-2 wirings live and on by default
        - chain_of_ideas_enabled = true                              [§6.1.T1]
        - novelty_gate_enabled = true                                [§6.1.T5]
        - pointwise_novelty_enabled = true                           [§6.4.T1]
        - persona_reviewers_enabled = true                           [§6.4.T1]
        - cascaded_review_enabled = true                             [§6.4.T1]
        - exploration_breadth_enabled = true                         [§6.2.T9]
        - traceability_mode = "full"                                 [§6.3.T5]
        - checklist_ethics: replaces freeform EthicsReviewNode       [§6.1.T6 + §6.5.T1]

[ ] (G2) make check passes
        - ruff clean
        - pyright clean (basedpyright)
        - pytest -m 'not medium and not large' green
        - pytest count ≥ 1500

[ ] (G3) make test-integration green (Docker tier)

[ ] (G4) make run-experiment TOPIC=<sample> produces a PDF in ≤ 2 hours, supervised, against LLM proxy
        - one full successful run captured at output/<run-id>/03-writing/manuscript.pdf

[ ] (G5) make resume THREAD_ID=<crashed-run> restores from any node
        - tested by killing mid-run and resuming

[ ] (G6) CHANGELOG entry for v2.5.0 written and dated
        - covers all §6 deltas
        - lists all 🔴 regressions from §19 with mitigation references
        - documents migration steps from §20

[ ] (G7) examples/ contains one runnable script per cross-cutting capability added
        - examples/run_with_acl_template.py                          [§6.12.T3]
        - examples/run_with_breadth_mode.py                          [§6.12.T3]
        - examples/inspect_cascade_verdict.py                        [§6.12.T3]
        - examples/replay_from_events_jsonl.py                       [§6.12.T3]

[ ] (G8) PRD §6 deltas all show every task as [x] or [skipped] with rationale
        - mark complete using the task IDs (6.1.T1, etc.) in the PR description
```

### 23.2 Output gates (matches §3.3 gates 9–12)

```
[ ] (G9) make test-regression Phase A green
        - all 5 golden fixture topics pass full structural-assertion suite
        - assertion library at tools/output_assertions.py             [§6.15.T3]

[ ] (G10) Every LLM-as-Judge has TPR ≥ 0.85 AND TNR ≥ 0.85 on its test split
        - hedge_language judge (FBR001)                              [§6.15.T6]
        - thesis_coherence judge (FBR002)                            [§6.15.T6]
        - persona_tone_mismatch judge (FBR003)                       [§6.15.T6]
        - citation_orphan judge (FBR004)                             [§6.15.T6]
        - fabricated_numeric judge (FBR005)                          [§6.15.T6]
        - imrad_completeness judge (FBR006)                          [§6.15.T6]

[ ] (G11) Bias-corrected pass rate has 95% bootstrap CI lower bound ≥ 0.70
        - per failure mode, on a rolling sample of latest 50 production runs
        - via Rogan-Gladen + judgy bootstrap                         [§6.15.T7]

[ ] (G12) Jackson signed off on 3 sample papers in docs/v2.5.0-spot-review.md
        - 3 of 3 boxes checked
        - one paper is a v2.4.0 vs v2.5.0 side-by-side eyeball       [§6.15.T10]
```

### 23.3 Migration safety (matches §19 + §20)

```
[ ] All 🔴 regressions from §19 have verified mitigations
        - R1, R3, R4, R5, R10, R17, R18, R20, R21, R22, R23, R29, R32

[ ] All migration scripts from §20 exist and have unit tests at tests/unit/tools/test_migrations.py
        - tools/check_version_consistency.py
        - tools/cleanup_state.py
        - tools/migrate_authors_yaml.py
        - tools/grep_orphan_imports.py
        - tools/audit_publish_yml.py (one-shot, audit complete)
        - tools/migrate_agent_cache.py
        - tools/dagster_workspace_cleanup.py

[ ] docs/architecture/migrations.md exists with the 9-step runbook    [§6.12.T9 + §20]
```

### 23.4 Documentation set complete

```
[ ] docs/architecture/recovery.md                                     [§6.6.T3]
[ ] docs/architecture/rendering.md                                    [§6.7.T7]
[ ] docs/architecture/sdk.md                                          [§6.12.T4]
[ ] docs/architecture/skills.md                                       [§6.12.T8]
[ ] docs/architecture/observability.md                                [§6.13.T4]
[ ] docs/architecture/release.md                                      [§6.14.T2 + §6.14.T5]
[ ] docs/architecture/traceability.md                                 [§6.10.T7]
[ ] docs/architecture/evaluation.md                                   [§6.15.T11]
[ ] docs/architecture/migrations.md                                   [§20]
[ ] docs/evaluation/failure-modes.md                                  [§6.15.T4b]
[ ] docs/v2.5.0-spot-review.md                                        [§6.15.T10] (signed)
[ ] docs/README.md refreshed as TOC for the doc set                   [§6.12.T9]
```

### 23.5 Pre-tag pre-flight script

```bash
# Run this exact sequence to verify all 4 sections above. Exit non-zero if anything fails.

set -euo pipefail

echo "G2 — quality gate"
make check

echo "G3 — Docker integration"
make test-integration

echo "G6 — CHANGELOG dated"
grep -q "^## \[2.5.0\] — 2026-" CHANGELOG.md

echo "G7 — examples"
for ex in examples/run_with_acl_template.py examples/run_with_breadth_mode.py examples/inspect_cascade_verdict.py examples/replay_from_events_jsonl.py; do
  test -f "$ex"
done

echo "G9 — regression suite Phase A (structural assertions)"
uv run python -m academic_pipeline.evaluation.regression --fixtures tests/fixtures/golden/ --strict

echo "G10 — judge alignment on test splits"
uv run python -m academic_pipeline.evaluation.alignment --judges all --on test --min-tpr 0.85 --min-tnr 0.85

echo "G11 — bias-corrected pass rate per failure mode"
uv run python -m academic_pipeline.evaluation.estimate --runs latest:50 --judges all --min-ci-lower 0.70

echo "G12 — Jackson signoff (3 boxes in spot-review)"
test "$(grep -c '^- \[x\]' docs/v2.5.0-spot-review.md)" = "3"

echo "Migration scripts present"
for s in check_version_consistency cleanup_state migrate_authors_yaml grep_orphan_imports audit_publish_yml migrate_agent_cache dagster_workspace_cleanup; do
  test -f "tools/$s.py"
done

echo "Architecture docs present"
for d in recovery rendering sdk skills observability release traceability evaluation migrations; do
  test -f "docs/architecture/$d.md"
done
test -f docs/evaluation/failure-modes.md
test -f docs/README.md

echo "Version coherence"
uv run python tools/check_version_consistency.py

echo ""
echo "All v2.5.0 tag-day gates passed. Safe to tag and push."
```

If this script exits 0, push the tag:

```bash
git tag -a v2.5.0 -m "v2.5.0 — see CHANGELOG.md"
git push origin v2.5.0
```

If any gate fails, **do not push the tag**. Identify which gate failed → trace through this PRD to the owning section → fix → re-run.

### 23.6 Post-tag

```
[ ] CHANGELOG entry for v2.6.0 created with [Unreleased] section
[ ] VERSION bumped to 2.6.0-dev (per §6.14.T6 tag protection rule on v2.5.0)
[ ] Spec 9 (cross-run memory) tracker started in §7 with paper-count gate (10 papers shipped)
[ ] Submit v2.5.0-generated paper(s) to SCI journal(s) — track outcomes in `docs/sci-submissions.md` (new)
```

---

## 24. Example Agent YAML Stubs

Verified against existing PydanticAI YAML format used in `src/academic_pipeline/<subgraph>/specs/*.yaml`. Loop should adapt these stubs rather than invent the structure from scratch.

### 24.1 LLM-as-Judge template (used for all 6 judges in §6.15.T6)

This is the canonical structure. Copy and specialize per failure mode. Saved at `src/academic_pipeline/evaluation/judges/specs/<failure_mode>.yaml`.

```yaml
model: anthropic:claude-opus-4-7
name: <failure_mode>_judge_agent
description: |
  Binary Pass/Fail judge for the <failure_mode> failure mode (FBR<NNN>).
  See docs/evaluation/failure-modes.md for the precise definition.
capabilities:
  - Thinking: { effort: high }      # judges use 'high' not 'xhigh' — they're binary classifiers, not generators
model_settings:
  max_tokens: 4000                  # judges output one JSON object; small budget is sufficient
  temperature: 0.1                  # low temperature = consistent verdicts on borderline cases
retries: 2
output_retries: 2
instructions: |
  # <Failure Mode Title> Judge

  You evaluate a single trace artifact for one specific failure mode.
  Output a binary Pass/Fail verdict with a one-to-two-sentence reasoning.

  ## Definition of Pass/Fail

  - **Fail**: <precise definition of when the failure mode is present>
  - **Pass**: <precise definition of when it is absent>

  ## What you evaluate

  You receive: <describe the input — the section text, the figure, the
  numeric claim, etc.>

  You do NOT evaluate: <explicitly list out-of-scope concerns to keep
  the judge narrow — per chapter 5, multi-criteria judges fail>

  ## Examples

  ### Pass example
  Input: <verbatim trace excerpt>
  Verdict: Pass
  Reasoning: <one sentence>

  ### Fail example
  Input: <verbatim trace excerpt>
  Verdict: Fail
  Reasoning: <one sentence>

  ### Borderline example (still Pass)
  Input: <verbatim trace excerpt>
  Verdict: Pass
  Reasoning: <one sentence explaining why borderline still counts as pass>

  ## Anti-patterns

  Do NOT:
  - score on tone unless this judge IS the tone judge
  - score on overall paper quality
  - score on multiple criteria in one verdict (one judge = one criterion)
  - return anything other than `Pass` or `Fail` in the answer field
  - skip the reasoning field
  - quote more than 200 characters of input in the reasoning

  ## Output schema

  Return exactly:

  {
    "reasoning": "<1-2 sentence explanation>",
    "answer": "Pass" | "Fail"
  }
```

### 24.2 Specific judge: hedge_language (FBR001)

Concrete instantiation of §24.1 for the `hedge_language_in_results` failure mode (§21).

```yaml
model: anthropic:claude-opus-4-7
name: hedge_language_judge_agent
description: |
  Binary Pass/Fail judge for hedge_language_in_results (FBR001).
  Detects hedge phrases that smuggle uncommitted findings into Results sections.
capabilities:
  - Thinking: { effort: high }
model_settings:
  max_tokens: 4000
  temperature: 0.1
retries: 2
output_retries: 2
instructions: |
  # Hedge Language Judge

  You evaluate one Results-section excerpt for hedge language that lets
  the writer commit a finding without committing to the underlying number.

  ## Definition of Pass/Fail

  - **Fail**: the excerpt contains one or more hedge phrases that defer
    the actual numeric finding to a future iteration. Examples of hedge
    phrases (non-exhaustive):
    - "interim results suggest"
    - "subject to revision"
    - "full search awaits"
    - "preliminary indications"
    - "approximately N% (final figure TBD)"
    - "we expect" / "we anticipate" (without supporting basis)
    - "near-final estimate of N"
  - **Pass**: every numeric claim is committed (no hedge), even if the
    underlying methodology is acknowledged with confidence intervals or
    standard caveats. CIs are NOT hedges. "Statistically significant
    (p < 0.05)" is NOT a hedge. "Did not reach significance" is NOT a
    hedge. "Limited by sample size of N" is NOT a hedge.

  ## What you evaluate

  Input is exactly one section body (markdown), typically Results, but
  may be Discussion or Conclusion. You do NOT need access to the full
  paper or the bibliography.

  You do NOT evaluate: tone (separate judge), citation completeness
  (separate judge), thesis coherence (separate judge), IMRaD structure
  (separate judge), or fabrication (separate judge — `fabricated_numeric`).

  ## Examples

  ### Pass
  Input: "AutoGluon achieved an AUROC of 0.847 (95% CI 0.821-0.873) on the
  held-out test set, outperforming the logistic regression baseline (AUROC
  0.762, p < 0.001 by paired t-test)."
  Verdict: Pass
  Reasoning: Numeric claims are committed with CIs and a paired test.
  Confidence intervals are not hedges.

  ### Fail
  Input: "Interim results suggest AutoGluon may outperform the baseline
  (AUROC ≈ 0.84, full search awaits). The improvement appears statistically
  significant subject to revision."
  Verdict: Fail
  Reasoning: "Interim", "may outperform", "≈", "full search awaits", and
  "subject to revision" are hedge phrases that defer commitment to the
  number itself.

  ### Borderline (Pass)
  Input: "The model achieved 0.84 AUROC on validation; final test-set
  performance is reported in Table 3."
  Verdict: Pass
  Reasoning: References a specific table for the final number rather than
  hedging — pointer to a committed result is not a hedge.

  ## Anti-patterns

  Do NOT:
  - flag confidence intervals or significance statements as hedges
  - flag standard methodology caveats ("limited by sample size") as hedges
  - score on whether the numbers themselves are correct (that's `fabricated_numeric`)
  - score on whether the section has citations (that's `citation_orphan`)

  ## Output schema

  Return exactly:

  {
    "reasoning": "<1-2 sentence explanation>",
    "answer": "Pass" | "Fail"
  }
```

### 24.3 Construction notes for the other 5 judges

| Judge | Failure mode | Input scope | Key anti-pattern (don't conflate with) |
|---|---|---|---|
| `thesis_coherence` (FBR002) | thesis_incoherence | full manuscript outline + Thesis Statement | tone (`persona_tone_mismatch`); fabrication (`fabricated_numeric`) |
| `persona_tone_mismatch` (FBR003) | persona_tone_mismatch | one section body + target_journal config | thesis (`thesis_coherence`); citations (`citation_orphan`) |
| `citation_orphan` (FBR004) | citation_orphan | one section body + bibliography | trace tokens (those count as grounding); fabrication |
| `fabricated_numeric` (FBR005) | fabricated_numeric | one numeric claim + ExperimentResults + bibliography | hedge language (`hedge_language`); citation orphans |
| `imrad_completeness` (FBR006) | imrad_incompleteness | manuscript section list + experiment-presence flag | tone; thesis; citations |

For each, instantiate §24.1 with: precise Pass/Fail definitions, 2-3 in-prompt few-shot examples drawn ONLY from the train split, narrow input scope, explicit "do NOT score on X" anti-patterns. Test against the dev split via §6.15.T5 alignment loop until TPR ≥ 0.85 AND TNR ≥ 0.85.

### 24.4 Loop directive for new agent YAMLs

When the loop creates a new agent YAML (a new judge, a Phase 2 cascade reviewer, etc.):

1. **Start from a verified existing YAML** as the structural template — never write from scratch. Existing references:
   - For reviewer-tier agents: `src/academic_pipeline/research/specs/independent_verifier.yaml`
   - For thinking-capable generators: `src/academic_pipeline/research/specs/chain_of_ideas_extractor.yaml`
   - For persona reviewers: `src/academic_pipeline/review/specs/senior_gatekeeper_reviewer.yaml`
   - For binary judges: §24.1 template above

2. **Use the verified API surface** from §13:
   - `model: anthropic:claude-opus-4-7` (with provider prefix)
   - `capabilities: [Thinking: { effort: <level> }]` for thinking
   - `model_settings.anthropic_effort: max` for the verifier tier (only)
   - `model_settings.max_tokens: <budget>` — 4000 for judges, 128000 for verifiers, default for generators
   - `retries` and `output_retries` for resilience
   - **Never** use deprecated `anthropic_thinking={'type': 'enabled', 'budget_tokens': N}` (broken on Opus 4.7 — see §13.3)

3. **Register in the subgraph's `agents.py`** — `Agent.from_file()` + `agents[agent_name] = agent`. For agents with `output_validator`, register the validator post-construction: `agents[name].output_validator(my_validator_fn)`.

4. **Add a unit test** that uses `agent.override(model=TestModel(custom_output_text=...))` per §13.1. Never set `agent.model =` directly.

5. **Add `output_type=PromptedOutput(MyPydanticModel)`** to the Python registration call when the agent emits structured output. The Pydantic model lives in the appropriate `models/<subgraph>.py`.

---

## 25. Logfire Span Schema

Parallel to §18 (events.jsonl). For every event the pipeline writes to events.jsonl, Logfire receives a corresponding span (per §18.4 multi-record-per-event invariant). This section is the canonical span schema. Drift breaks Logfire dashboards, saved searches, and anyone using Logfire to debug a run.

### 25.1 Universal span attributes

Every span (regardless of type) carries:

| Attribute | Type | Source | Notes |
|---|---|---|---|
| `service.name` | string | `logfire.configure(service_name=...)` | `"academic-pipeline"` |
| `service.version` | string | from `pyproject.toml::version` | bumped per §6.12.T6 |
| `pipeline.run_id` | string | `PipelineState.run_id` | matches `events.jsonl` `run_id` |
| `pipeline.thread_id` | string | `PipelineState.thread_id` | resume key |
| `pipeline.stage` | string | current stage when span fired | `research`, `experiment`, `writing`, `review`, `integrity`, `""` |

### 25.2 Span types

#### Inherited from PydanticAI's `instrument_pydantic_ai()`

PydanticAI emits these automatically — we do not produce them:

- `agent.run` — outermost agent invocation
- `model_request` — single model call
- `tool_call` — single tool invocation
- (per PydanticAI docs) — see https://ai.pydantic.dev/logfire/

We add the following attributes to every PydanticAI-emitted span via per-agent instrumentation (§6.13.T3):

| Attribute | Source |
|---|---|
| `agent.name` | the YAML `name:` field of the agent |
| `agent.type` | `"generator"` \| `"reviewer"` \| `"verifier"` \| `"judge"` |
| `agent.effort` | `model_settings.anthropic_effort` if set, else the `Thinking.effort` capability value |
| `agent.max_tokens` | `model_settings.max_tokens` if set |

#### Custom spans we emit (mirroring §18.2 events.jsonl types)

For each event in §18.2, a Logfire span is emitted with the **same name as the event_type** (per §18.4 invariant). Span attributes match the JSON fields of the corresponding event.

##### `pipeline_start` span
```python
with logfire.span("pipeline_start",
                  run_id=run.run_id, topic=topic, resumed=False):
    ...
```

##### `node_complete` span
```python
with logfire.span("node_complete",
                  stage=stage, node=node_name, scope=scope,
                  duration_s=elapsed):
    ...
```

##### `recovery_event` span (NEW v2.5.0; §6.13.T1)
```python
logfire.info("recovery_event",
             layer=layer_num,
             action=action,            # "kill"|"resume"|"abort"
             reason=reason_text,
             strike=strike_num,
             error_code="REC004")
```
Note: emitted as a single `info` log entry (no enclosing span) because recovery events are point-in-time, not durations.

##### `cascade_verdict` span (NEW v2.5.0)

Per `docs/superpowers/specs/2026-05-03-cascaded-reviewer-design.md` (verified ralph-31), the cascade has **4 stages** (A/B/C/D = NUMERICAL_GROUNDING/NOVELTY/METHODOLOGY/NARRATIVE) and the verdict enum has **4 values** (not pass/fail):

```python
with logfire.span("cascade_verdict",
                  stage=stage_letter,           # "A"|"B"|"C"|"D"
                  stage_name=stage_name_enum,   # "numerical_grounding"|"novelty"|"methodology"|"narrative"
                  verdict=verdict_enum,         # "pass"|"short_circuit_reject"|"skipped"|"not_run"
                  short_circuited=bool):
    if verdict == "short_circuit_reject":
        logfire.error("cascade_verdict_short_circuit",
                      reason=reason_text,
                      error_code="CAS001")    # CAS-A; CAS002 for B; CAS003 for C
```

Note: Stage D (NARRATIVE) is the leaf stage and does NOT short-circuit subsequent stages (there are none). Its verdict feeds the final editorial synthesis only. `cascade_short_circuit_on_stage_a/b/c` config flags exist (verified `config.py:151-155`); there is no `cascade_short_circuit_on_stage_d` because Stage D has nothing to short-circuit.

##### `judge_alignment` span (NEW v2.5.0)
```python
with logfire.span("judge_alignment",
                  judge=judge_name,
                  split=split_name,
                  n=sample_size):
    logfire.info("alignment_metrics",
                 tpr=tpr, tnr=tnr,
                 warning=(tpr < 0.85 or tnr < 0.85),
                 error_code="EVL002" if tpr < 0.85 else None)
```

##### `regression_result` span (NEW v2.5.0)
```python
with logfire.span("regression_result",
                  phase=phase_letter,           # "A"|"B"|"C"
                  fixture=fixture_slug,
                  judge=judge_name):
    if not passed:
        logfire.error("regression_fail",
                      ci_lower=ci_lower,
                      error_code="EVL003")
```

(Schemas for `doi_gate_failure`, `novelty_gate_verdict`, `ethics_checklist_result`, `design_bundle_scores` follow the same one-attribute-per-event-field pattern.)

### 25.3 Naming conventions

- **Span name** == **events.jsonl `type` field** (e.g., `cascade_verdict`). This lets a Logfire query like `service.name = academic-pipeline AND span.name = cascade_verdict AND verdict = fail` find the same records as `jq 'select(.type=="cascade_verdict" and .verdict=="fail")' events.jsonl`.
- **Snake_case attribute names** matching the events.jsonl JSON field names exactly.
- **No camelCase, no kebab-case**, no spaces.

### 25.4 Saved Logfire searches (recommended)

Add these to the Logfire project after v2.5.0 ships (`docs/architecture/observability.md` §6.13.T4 should list them):

| Search name | Query |
|---|---|
| Recent failures | `service.name = academic-pipeline AND level >= error` |
| Cascade Stage A failures | `span.name = cascade_verdict AND stage = A AND verdict = fail` |
| Hedge-language vetos | `attribute.error_code = QGT003` |
| Trace-token misses | `attribute.error_code STARTS WITH "TRC"` |
| DOI gate failures | `span.name = doi_gate_failure` |
| Recovery fires (any layer) | `span.name = recovery_event` |
| Per-agent latency | `service.name = academic-pipeline AND span.name = agent.run GROUP BY agent.name` |
| Judges with low TPR | `span.name = alignment_metrics AND tpr < 0.85` |

### 25.5 Loop directive for Logfire spans

When the loop adds a new pipeline event:
1. Add the event type to §18.2 with full JSON shape.
2. **Also add the corresponding span** to §25 with attribute-by-attribute mapping.
3. Wire emission in code so events.jsonl record + Logfire span fire together within ±1 second (§18.4 invariant).
4. If the event represents a failure, attach the `error_code` from §17 to BOTH.
5. Update `docs/architecture/observability.md` saved-searches section if a new search makes sense.

Skipping the Logfire span side means the event exists in events.jsonl but is invisible to anyone using Logfire — half the observability surface.

---

## 26. Decision Log

For each major architectural choice, why we picked it over the alternatives. The loop must not "improve" any of these by switching to the rejected alternative without an explicit override directive from Jackson — every choice here was made deliberately and reverting is high-cost.

| ID | Decision | Picked | Rejected | Why |
|---|---|---|---|---|
| D1 | Pipeline orchestration | `pydantic-graph` | LangGraph, AutoGen, CrewAI, Prefect | Same vendor as PydanticAI; type-safe `BaseNode[StateT, DepsT, RunEndT]`; native integration with state persistence + resume; no extra runtime |
| D2 | Agent framework | PydanticAI | LangChain, LlamaIndex, OpenAI Assistants, raw Anthropic SDK | Pydantic-native typed I/O, `PromptedOutput` for structured output even on Thinking-effort models, `Agent.from_file()` YAML specs, native Logfire integration |
| D3 | Primary LLM | Claude Opus 4.7 | GPT-5.2, Gemini 3, multi-provider mix | Best in class for thinking-effort + max-effort modes; `anthropic_effort: max` is one tier above `xhigh` and catches things `xhigh` misses; v2.4.0 dropped GPT-5.2 fallback because both verifier legs were Opus already |
| D4 | Structured output mode | `PromptedOutput(Model)` | Native Anthropic tool-use structured output, JSON-mode | PromptedOutput is Thinking-compatible (native tool-use is not, on some models); two-stage validation (Pydantic schema + custom output_validators); works uniformly across providers |
| D5 | Thinking config | Adaptive thinking + `anthropic_effort` | Extended thinking with `budget_tokens=N` | Extended thinking with `budget_tokens` is REMOVED on Opus 4.7; adaptive is the only path forward; effort levels (low/medium/high/xhigh/max) replace budget tuning |
| D6 | Effort tier strategy | `anthropic_effort: max` for reviewer/verifier ONLY; generators use `Thinking: { effort: xhigh }` | Max for everyone | Max effort doubles thinking-token cost; only worth it where the goal is catching subtle errors (verifier) not creative output (generator) |
| D7 | Experiment substrate | Dagster + DuckDB + AutoGluon + MLflow + DVC | Custom Python script, Prefect, Airflow, Metaflow, Kedro | Dagster `@asset` + `@asset_check` give per-step re-materialization on failure (replaces v2.4.0's lose-8.5min-per-failure problem); MLflow `autolog()` captures params+metrics+artifacts+models without explicit instrumentation; DVC pins HF dataset hashes per run for reproducibility |
| D8 | Data layer | DuckDB + Arrow | Pandas, Polars | DuckDB IS the columnar engine — Arrow is the zero-copy boundary to numpy/AutoGluon; Polars adds a third dataframe to the stack; Pandas does not scale to dataset sizes we may hit |
| D9 | ML AutoML | AutoGluon | Ludwig, AutoSklearn, FLAML | Three native predictors (Tabular/TimeSeries/MultiModal) cover all 5 problem-type slots; auto model selection + ensembling; declarative API matches the YAML config-writer pattern |
| D10 | Sandboxing | Optional Docker, default off (Phase 2) | Docker mandatory, gVisor, nsjail | Agent only writes YAML/SQL (both bounded) post-Dagster cutover, not arbitrary Python — sandboxing is overkill for declarative configs; optional Docker stays for paranoia |
| D11 | Search provider | Exa direct via `tools/bibliography/exa.py` | `pydantic-ai-slim[exa]` ExaToolset, DuckDuckGo, Tavily | Direct API gives us full control over result filtering, retries, dedup; pydantic-ai-slim[exa] migration is a v2.6.0 candidate (see §13.4) but not v2.5.0 scope |
| D12 | DOI verification | CrossRef API direct | DataCite, OpenAlex, Semantic Scholar metadata | CrossRef is the registry of record for DOIs; rate-friendly (no key required for verification); other sources are derivative |
| D13 | Novelty signal | Semantic Scholar title similarity | Local embedding similarity over our archive, OpenAlex citation graph | S2 is the broadest scholarly index; title similarity is cheap + interpretable; embedding similarity over our archive only works post-§7 cross-run memory |
| D14 | LLM-as-Judge bias correction | `judgy` PyPI install | Port the algorithm into our codebase, skip correction entirely | judgy is numpy-only (no transitive deps); maintained by the chapter 5 author; porting just to avoid one dep is bikeshedding |
| D15 | Judge structure | One failure mode per binary judge | Multi-criteria 1-5 Likert judge | Per chapter 5: multi-criteria judges have ambiguous TPR/TNR; binary Pass/Fail aligns cleanly with TPR/TNR + Rogan-Gladen correction; one-failure-per-judge keeps prompts narrow and refinable |
| D16 | Trace dataset labeling | Single domain expert (Jackson) | Multi-annotator with inter-annotator agreement | Per chapter 3: single trusted expert is the most efficient path; we don't have a labeling team; Jackson IS the domain expert |
| D17 | True pass rate estimation | Bias-corrected via Rogan-Gladen + bootstrap CI | Raw judge pass rate, F1 score | Raw rate is biased by judge errors; F1 conflates the two error modes (TPR/TNR) that bias correction handles separately; CI surfaces uncertainty rather than hiding it |
| D18 | A/B comparison v2.4.0 ↔ v2.5.0 | Eyeball one paper side-by-side in spot-review | Paired t-test over 25 runs across 6 metrics | For a single-author project, formal A/B testing is overkill; the gate is "is v2.5.0 better"; Jackson reading two papers is cheaper, faster, and the actual quality signal |
| D19 | PDF compilation | pandoc + tectonic | latexmk, pdflatex, XeLaTeX, Typst | Tectonic auto-fetches LaTeX packages (no system tex install); pandoc handles markdown→LaTeX cleanly; both are stable + maintained; Typst is too new |
| D20 | Bibliography style | Numbered citations in markdown body, expanded by `citation_resolver` | pandoc `--citeproc`, citeproc-py | Citation_resolver is bibliography-aware (a `[token]` is a cite iff the token is in the bib) — eliminates false-positive matches from regex citeproc; gives us per-merge control over adjacent-cite formatting |
| D21 | Hang recovery | 4-layer system (TCP keepalive + bounded `agent.run` + heartbeat + watchdog) | LangChain retry decorators, Tenacity, restart-on-failure | The 1h+ wedged-in-recv class against LLM proxy is below LangChain/Tenacity's detection layer (the request looks alive); only OS-level keepalive + process-level supervision catch it |
| D22 | Process supervisor | Sibling subprocesses with `os.setsid` per process group | systemd units, supervisord, systemd-nspawn | Per-run process groups give us SIGTERM/SIGKILL targeting that kills the agent + every tool-call subprocess atomically; systemd is overkill for a per-user CLI tool |
| D23 | Crash recovery | File-based `SqliteStatePersistence` + `AgentMessageCache` | SQLite alone, Redis, durable execution (Temporal) | Files are inspectable (the loop can read them with the Read tool); SQLite is for the per-run snapshot of pipeline-graph state, not for the per-agent message history (that's the cache); Temporal/durable-execution is overkill |
| D24 | State serialization | `pydantic.TypeAdapter` + `ModelMessagesTypeAdapter` | Pickle, custom JSON encoders, msgpack | TypeAdapter handles all our Pydantic models without bespoke encoders; ModelMessagesTypeAdapter is the canonical PydanticAI persistence path; Pickle is unsafe across versions |
| D25 | Pipeline event log | Append-only `events.jsonl` per run | SQLite event table, structured logging only, time-series DB | jsonl is greppable + tailable + survivable across crashes; one file per run scopes naturally; dashboards are pure renderers; SQLite would lock-fight the watchdog |
| D26 | Dashboard | Rich-rendered `dashboard.txt` snapshot + React v2 (deferred) | Curses, Streamlit | Rich gives us terminal-rendered tables in a CLI without a server; React v2 is the future for richer browsing but non-blocking for v2.5.0; Streamlit needs Python-running on the operator side |
| D27 | Config layering | pydantic-settings with explicit precedence (init > env > .env > dev.yaml > default.yaml) | Hydra, OmegaConf, dynaconf | pydantic-settings is the only one with first-class Pydantic validation; explicit precedence prevents mystery overrides; YamlConfigSettingsSource is built-in |
| D28 | Failure-mode taxonomy origin | Open coding + axial coding on actual production traces (chapter 3) | Off-the-shelf LLM failure categories (hallucination, instruction-following, etc.) | Per chapter 3: generic categories miss application-specific issues; the 6 modes locked in §6.15.T4b are derived from `feedback_*` memory entries that surfaced in real runs |
| D29 | DBOS durable execution | Disabled (per `project_dbos_compat` memory) | Enable as a `pydantic-ai[dbos]` extra | DBOS conflicts with `asyncio.gather` cancel scope (concrete bug observed); fix would require sequential evaluator mode under DBOS, which removes the parallelism gain — net negative; revisit when DBOS resolves the cancel-scope conflict upstream |
| D30 | Spec 9 (cross-run memory) | Deferred until 10 papers shipped | Build now alongside other Phase 2 wirings | Memory only useful when there's a corpus to learn from; building it before 10 papers is premature optimization (per the spec's own design doc); explicit non-goal #N7 prevents the loop from opportunistically scoping it |

### How to use this section

When the loop encounters a delta that touches one of these decisions:
1. Read the row before proposing changes.
2. If the change reverses the decision, surface to Jackson FIRST — do not silently switch.
3. If the change is consistent with the decision, proceed.
4. New major architectural choices made during v2.5.0 work MUST add a new D-row in the same PR.

### Decisions not yet made (open)

| Tag | Open question | Default if unanswered |
|---|---|---|
| Q1 | Should `pydantic-ai[mcp]` extra be removed? | Yes (per §6.12.T7), pending audit |
| Q2 | Should we migrate from `tools/bibliography/exa.py` direct to `pydantic-ai-slim[exa]` ExaToolset? | No for v2.5.0 (out of scope); revisit v2.6.0 |
| Q3 | Should the React dashboard v2 ship in v2.5.0 or defer? | Defer if blocking; non-blocking otherwise |
| Q4 | Should we add a 7th failure mode based on PhD teammate feedback? | Surface to Jackson at spot-review; do not auto-add |
| Q5 | Should DOI gate fail-open if CrossRef is down? | Fail-closed by default; `--allow-unverified-dois` escape hatch (per R17) |
| Q6 | Should examples/ scripts be runnable in CI? | Dry-run mode in CI per §6.12.T3; full run only in `make test-large` |

When the loop has enough context to answer one of these, propose an answer in the PR description and append a new D-row.

---

## 27. Token Budget and Cost Estimates

For cost forecasting, rate-limit planning, and "is this delta worth the API spend" decisions. **All numbers are rough — actual cost varies ±30% with topic complexity, retry rate, and the new Opus 4.7 tokenizer (up to 35% more tokens than 4.6 for identical text).**

### 27.1 Anthropic pricing (verified against platform.claude.com 2026-05-06)

| Tier | Input ($/M tokens) | Output ($/M tokens) | Notes |
|---|---|---|---|
| Standard | $5.00 | $25.00 | Same as Opus 4.6 |
| Cache read | $0.50 | (n/a) | 90% discount; activated when prompt prefix is reused within 5-min cache window |
| Batch (50% off) | $2.50 | $12.50 | Async batch processing; not used for interactive pipeline runs |

**Thinking tokens bill as output.** A call with 3k visible output + 25k thinking tokens costs `(3k + 25k) × $25/M = $0.70` for output, plus input.

### 27.2 Per-agent-type budget

| Agent type | Effort | `max_tokens` | Typical input (tokens) | Typical visible output | Typical thinking | Cost / call ($) | Used by |
|---|---|---|---|---|---|---|---|
| **Generator** (research, writing, experiment design) | `Thinking: { effort: xhigh }` | default (8k–32k) | 4k–8k | 2k–4k | 8k–15k | ~$0.30 | most agents in §6.1, §6.2, §6.3 |
| **Heavy generator** (bibliography, draft_writer with full context) | `Thinking: { effort: xhigh }` | up to 32k | 20k–40k | 5k–10k | 15k–25k | ~$0.85 | `bibliography`, `draft_writer`, `formatter` |
| **Reviewer** (persona reviewers, editorial_synthesizer) | `model_settings.anthropic_effort: max` | default | 10k–20k | 3k–5k | 20k–35k | ~$0.85 | §6.4 reviewer YAMLs |
| **Verifier** (independent_verifier, figure_verifier) | `model_settings.anthropic_effort: max` | 128000 | 40k–80k | 5k–10k | 25k–50k | ~$1.50 | §6.11 verifier YAMLs |
| **Eval panel** (per-node evaluator) | default (no Thinking capability) | default (8k) | 3k–6k | 1k–3k | 3k–8k | ~$0.20 | `runtime/evaluator.py` |
| **Judge** (LLM-as-Judge in §6.15) | `Thinking: { effort: high }` | 4000 | 2k–5k | 100–500 | 1k–3k | ~$0.08 | `evaluation/judges/specs/*.yaml` |

### 27.3 Per-pipeline-run cost

For one complete `make run` invocation (intake → finalize):

| Subgraph | Generator calls | Reviewer calls | Verifier calls | Eval panel calls | Sub-total |
|---|---|---|---|---|---|
| §6.1 Research (with §6.13.T1 chain-of-ideas Phase 2) | ~12 | 0 | 1 | ~15 | ~$5.50 |
| §6.2 Experiment (when triggered, Phase 2 breadth K=2) | ~10 (×2 for breadth) | 0 | 1 (figure_verifier) | ~6 | ~$8.00 |
| §6.3 Writing | ~22 (8 sections × ~3 iterations) | 1 (peer_reviewer) | 1 (figure_verifier) | ~25 | ~$15.00 |
| §6.4 Review (Phase 2: cascade + persona + pointwise) | 0 | ~10 (3 personas + 3 cascade + 4 pointwise) | 0 | ~5 | ~$10.00 |
| §6.5 Integrity | ~3 (claims + plagiarism + ethics_checklist) | 0 | 0 | ~3 | ~$1.50 |
| **Total per run** | **~46** | **~11** | **~3** | **~54** | **~$40** |

That tracks with the README's "$15–$40 per run" with the Phase 2 wirings landing on the upper end.

### 27.4 Per-regression-suite cost (manual / pre-tag, §6.15)

| Phase | Calls | Cost |
|---|---|---|
| Phase A (structural assertions) | 0 LLM calls | $0 (pure code) |
| Phase B (judge alignment on test split) | 6 judges × ~75 dev/test traces × 1 call = 450 judge calls | ~$36 |
| Phase C (production estimate, 50 runs × 6 judges × ~5 sections per run) | 1500 judge calls | ~$120 |
| Phase D (anti-overfit guard) | 0 LLM calls | $0 |
| Phase E (3-paper spot review) | 0 LLM calls | $0 (Jackson reads) |
| Plus the 5 fixtures themselves at ~$40 each | 5 full runs | ~$200 |
| **Total per regression suite invocation** | | **~$355** |

Pre-tag the regression suite runs once. Weekly `make realign` per §6.15.T12 adds 6 × 10 traces = 60 judge calls = ~$5/week.

### 27.5 v2.5.0 development cost forecast

| Bucket | Estimate |
|---|---|
| Phase 0 labeling (Jackson reads 100+ traces; no API calls beyond what already produced them) | $0 |
| Phase 1–5 implementation runs (debug + smoke during dev) | ~$500 |
| Per-fixture A/B for Phase 6 (Jackson eyeballs, no formal A/B but he reads paired runs) | ~$200 |
| Pre-tag regression suite | ~$355 |
| Spot-review papers (3 fresh runs to read) | ~$120 |
| **Total v2.5.0 ship cost** | **~$1200** |

Per CLAUDE.md, the existing run cost is $15–$40. v2.5.0 raises the upper end to ~$50 with Phase 2 wirings (more reviewers, deeper cascade).

### 27.6 Rate-limit planning

Anthropic's tier-4 default rate limit on Opus 4.7 is roughly:
- 100 RPM (requests per minute)
- 400k ITPM (input tokens per minute)
- 80k OTPM (output tokens per minute)

Per pipeline run (~115 calls over 1–2 hours), that's well under the per-minute caps. Concurrent runs (e.g., breadth-mode K=2 firing parallel Dagster experiments) can push closer — verify with `tool_call_delay_seconds: 10` (already configured) staying in place.

§6.2.T5 K-parallel design fan-out doubles the experiment-subgraph call rate — confirm rate-limit headroom before flipping `exploration_breadth_enabled` default to `true`.

### 27.7 Loop directive for budget

When the loop adds a new agent or increases `max_tokens` on an existing one:
1. Add an entry to §27.2 (agent type) or extend the call-count in §27.3.
2. Re-check the per-run total. If it pushes past $50, surface to Jackson.
3. Confirm the new agent's effort tier is justified per §27.2 — generators don't need `max`, judges don't need `xhigh`.
4. Re-check rate-limit headroom in §27.6.

Token budget growth is a measurable cost regression and should be treated like any other R-row in §19.

---

## 28. Anti-Pattern Catalog (Consolidated)

Single searchable list of every "do not do this" rule scattered across the PRD. The loop reads sections sequentially and may miss anti-patterns from sections outside its current focus. This catalog is the safety net.

When the loop is about to merge a delta, it MUST grep this section for any anti-pattern keyword that appears in the delta's diff. If any AP-row matches, surface it before merging.

| ID | Anti-pattern | Source section | What to do instead |
|---|---|---|---|
| **AP1** | `@agent.tool` without `RunContext` first param | §13.2 | Use `@agent.tool` only when ctx needed; else `@agent.tool_plain` |
| **AP2** | `@agent.tool_plain` WITH `RunContext` first param | §13.2 | Switch to `@agent.tool` |
| **AP3** | Model string without provider prefix | §13.2 | `"anthropic:claude-opus-4-7"`, never `"claude-opus-4-7"` |
| **AP4** | Setting `agent.model = TestModel()` directly | §13.2 | `with agent.override(model=TestModel(...))` always |
| **AP5** | `output_type` union including `str` when forced structured output is required | §13.2 | Omit `str` from the union |
| **AP6** | `hooks.on.on_run_error` (doubled `on_`) | §13.2 | `hooks.on.run_error` |
| **AP7** | `history_processor=...` (singular) | §13.2 | `history_processors=[...]` (plural list) |
| **AP8** | Per-call `output_validators=[...]` arg to `agent.run()` | §13.2 | `agent.output_validator(fn)` post-construction registration |
| **AP9** | `anthropic_thinking={'type': 'enabled', 'budget_tokens': N}` on Opus 4.7 | §13.2 + §13.3 | Adaptive thinking is default on 4.6+; do not pass `budget_tokens` (REMOVED on 4.7) |
| **AP10** | Calling `agent.run()` outside `traced_agent_run` / `bounded_agent_run` | §13.2 | `await traced_agent_run(agent, ...)` |
| **AP10b** | Raising `_AGENT_RUN_TIMEOUT_S` ≥ `WatchdogConfig.max_idle_s` | §3.2 | Watchdog SIGKILLs the process group BEFORE bounded_run can raise `AgentTimeoutError`, corrupting the in-flight snapshot. Strict `<` ordering required: trace_logger 480 < watchdog 600 |
| **AP10c** | Hard-coding agent-run timeout in caller code | §3.2 | Always thread through `_AGENT_RUN_TIMEOUT_S` (trace_logger.py:21) so the L2/L4 ordering invariant is enforced at one site |
| **AP11** | Inventing tool names not in the registered tool registry | §13.2 | Reference only explicitly-registered tools / capabilities |
| **AP12** | Multi-criteria single LLM-as-Judge prompt | §13.2 + §6.15 + §24.1 | One failure mode per judge, binary Pass/Fail |
| **AP13** | Using dev/test traces as few-shot examples in a judge prompt | §13.2 + §6.15.T13 | Few-shot strictly from train split; CI guard at §6.15.T13 |
| **AP14** | Likert 1–5 scale in early labeling | §13.2 + chapter 3 | Binary Pass/Fail (acceptable / unacceptable) |
| **AP15** | Generic synthetic queries ("Generate 5 paper topics") | §6.15 + chapter 3 | Dimension-tuple-query method (§6.15.T1) |
| **AP16** | Skipping open coding for off-the-shelf metrics ("hallucination", "instruction-following") | §6.15 + chapter 3 | Failure modes must come from reading actual traces |
| **AP17** | Freezing failure-mode taxonomy too early | §6.15 + chapter 3 | Expect 2–3 iteration rounds (§6.15.T4d) |
| **AP18** | Outsourcing labeling to non-domain experts | §6.15 + chapter 3 | Single trusted expert (Jackson); no labeling team |
| **AP19** | Reporting dev-split TPR/TNR as judge quality | §6.15 + chapter 5 | Always measure on the held-out test split, after locking the prompt |
| **AP20** | Touching a file not listed in §15 Files Inventory | §15 | Either the plan is wrong or the inventory is incomplete — investigate before merging |
| **AP21** | Producer writes `state.thesis` while consumer reads `state.thesis_statement` | §16 | Use verified Pydantic class names from §16; assert non-None at every consumer site when flag is on |
| **AP22** | Renaming a state field after v2.5.0 | §16 | SemVer-breaking; wait for v3.0.0 |
| **AP23** | Inventing ad-hoc error strings ("writing_failed", "review_error") | §17 | Allocate next code in correct namespace; define exception class with `error_code` attribute |
| **AP24** | Renaming an error code after ship | §17 | Codes are immutable; deprecate + allocate new |
| **AP25** | Emitting an error without tagging events.jsonl + Logfire span with code | §17 + §18 + §25 | Both records carry the same `error_code` |
| **AP26** | Adding a field to an existing event type and breaking consumers | §18 | Forward-compat: consumers tolerate unknown fields; producers don't change/remove existing fields in minor versions |
| **AP27** | Skipping the events.jsonl `version` first-line marker | §18.1 | Emitted as first record; mismatched majors → DSH001 |
| **AP28** | Reading the last line of events.jsonl without try/except JSONDecodeError | §18.5 | Mid-write crash → tolerate malformed final line |
| **AP29** | Merging a 🔴 regression without verified mitigation | §19 | Revert the entire Phase 2 wiring rather than ship partial breakage |
| **AP30** | Deleting user data without archive | §20 | Default mode is archive (`.pipeline_runs/_archive/<ts>/`); only `--purge` actually deletes |
| **AP31** | Skipping `tools/grep_orphan_imports.py` before deletion | §20 | Run before any file deletion; orphan callers fail-fast at type-check |
| **AP32** | Silently expanding a failure-mode definition when reviewers flag adjacent issues | §21 | Add a 7th failure mode + new labels + new judge instead |
| **AP33** | Moving a test from small → medium without updating CI | §22 | Tier discipline: small (every PR) / medium (merge to main) / large (manual) / regression (pre-tag) |
| **AP34** | "Almost passes on real APIs" → `@pytest.mark.medium` with retry | §22.6 | If it needs real APIs it's `@pytest.mark.large`, full stop |
| **AP35** | Pushing v2.5.0 tag with output gates ungated | §23 | Pre-flight bash script must exit 0 (all 17 checks); spot-review file must show 3 of 3 boxes |
| **AP36** | Writing a new agent YAML from scratch | §24.4 | Start from a verified existing YAML (4 reference paths); use API surface from §13 |
| **AP37** | Adding a new event without adding the corresponding Logfire span | §25.5 | Both must fire within ±1s of each other |
| **AP38** | Reversing a §26 D-row's decision silently | §26 | Surface to Jackson before switching; add a new D-row if change ratified |
| **AP39** | Increasing `max_tokens` on existing agent without re-checking §27 budget | §27 | Per-run total >$50 surfaces to Jackson; check rate-limit headroom |
| **AP40** | Silently downgrading from `anthropic_effort: max` to a lower tier on a verifier | §27 + §6.11 | Verifier tier exists for a reason (catching subtle errors); downgrade requires Jackson approval |
| **AP41** | Force-pushing to main, amending shipped commits, `git reset --hard` on shared branches | global | Always work on a feature branch; PR with reviewer eyes; never force-push main |
| **AP42** | Skipping git hooks (`--no-verify`) | global | Pre-commit catches lint/format issues; bypassing them defers errors to CI / production |
| **AP43** | Letting an autonomous loop scope into a §3.2 Non-Goal (web frontend, multi-paper portfolio, etc.) | §3.2 | Non-goals are explicit; loop must HALT and surface if running out of in-scope work |
| **AP44** | Starting work on Spec 9 before 10 papers ship | §7 | Spec 9 is deferred; explicit non-goal #N7; do not opportunistically scope in |
| **AP45** | Replacing Anthropic / Dagster / DuckDB / AutoGluon as the substrate | §3.2 N6/N10 + §26 | These are non-goals + locked decisions; substrate swap requires user directive |
| **AP46** | Adding `from __future__ import annotations` to a module containing `@asset`/`@asset_check` | §6.2 + ralph-67 | Dagster's `@asset` decorator does identity comparisons on annotations at runtime; PEP 563 deferred annotations break the check. The agent-generated `assets/experiment/*` modules MUST omit the future import — even though the rest of the codebase uses it universally |
| **AP47** | Modernizing CSV reads to default DuckDB options | §6.2 + ralph-67 | `data_load.py` uses `sample_size=-1` + `null_padding=true` deliberately — defaults silently corrupt datasets with widening type ranges (rossmann StateHoliday case verified) |
| **AP48** | Replacing `yaml.safe_load` with `yaml.load` | §6.2 + ralph-66 | Security-critical: `yaml.load` allows arbitrary code execution from a malicious config.yaml |
| **AP49** | Splitting `experiment.duckdb` into multiple per-phase .duckdb files | §6.2 + ralph-66 | Single-store invariant enables cross-asset SQL JOINs without cross-database setup |
| **AP50** | Generating MLflow asset code without `mlflow.start_run(nested=True)` | §6.2 + ralph-66 | Without `nested=True`, MLflow run hierarchy collapses — every asset becomes a sibling root instead of a child of the orchestrating job run |
| **AP51** | Adding algorithm-specific fields (problem.type, AutoGluon presets, metric specs) to `config_models.py` | §6.2 + ralph-65 | `config_models.py` is orchestration-only by design. Algorithm config goes inside the agent-generated `@asset` modules. Adding to the schema would gut the agent's code-generation flexibility |
| **AP52** | Writing trace files to a flat directory instead of `output/<run_id>/<phase>/traces/{NN}_{name}.{md,json}` | §6.13 + ralph-68 | Sequence-prefixed per-phase layout is consumed by dashboard/audit tooling; flat dirs lose ordering and collide on agent-name reuse |
| **AP53** | Truncating `tool-return` content in the raw JSON trace file | §6.13 + ralph-68 | Truncation is markdown-only (`_MAX_TOOL_RESULT_CHARS = 3000`); raw JSON MUST preserve full content for post-hoc replay/forensics |
| **AP54** | Removing the 3-fallback message-serialization ladder in `TraceLogger.log` | §6.13 + ralph-68 | Trace writes must NEVER raise — losing a trace blinds the operator. Three fallbacks: `all_messages_json()` → `model_dump()` loop → placeholder. Removing any layer recreates the silent-trace-loss bug |
| **AP55** | Adding a new `part_kind` to PydanticAI agent messages without extending `_format_readable` | §6.13 + ralph-68 | The dispatch in `runtime/trace_logger.py:178` is exhaustive over the 8 known part_kinds; unknown kinds silently produce empty markdown sections. Add a branch per new kind |
| **AP56** | Vetoing `[PENDING: ...]` markers as forbidden placeholders | §6.11 + ralph-69 | `[PENDING: ...]` is the SANCTIONED deferral form per `writing/specs/section_writer.yaml line 67-75`. The `[INSERT...]` regex is hand-tuned to NOT match `[PENDING: ...]`. Loop extending placeholder vetos MUST preserve the carve-out; breaking it blocks legitimate agent deferral markers |
| **AP57** | Mutating `EvaluationResult.scores` when applying a hard veto | §6.11 + ralph-69 | `apply_hard_vetos` MUST preserve `scores` unchanged for postmortem visibility. Only `verdict`, `feedback`, `weakest_dimension` are overridden. `EvaluationResult` is `frozen=True`, so the function returns a NEW instance — loop must NOT in-place-mutate or reset scores to placate downstream consumers |
| **AP58** | Treating `weakest_dimension == "hard_veto"` as a real rubric dimension | §6.11 + ralph-69 | `"hard_veto"` is a sentinel value (not in any rubric). Dashboard / score_trajectory / per-node analysis MUST special-case it as structural-failure, not aggregate it into dimension averages |
| **AP59** | Hard-coding placeholder/LaTeX patterns in evaluator instead of `runtime/hard_vetos.py` | §6.11 + ralph-69 | Vetos live ONLY in `runtime/hard_vetos.py` for single-source-of-truth. Agents adding "if pattern in text: fail" inline create silent divergence between evaluator and validators paths |
| **AP60** | Removing the `_BARE_LATEX_RE` math-whitelist filter (vetoing all bare `\command`s) | §6.11 + ralph-69 | Text-mode commands (`\textbf`, `\textit`, `\section`) are LEGAL in markdown→LaTeX renders. Veto only fires on the 60+ math symbols whitelist; broadening it would falsely fail every section header that survives pandoc round-trip |
| **AP61** | Adding a dimension to `score_trajectory.DIMENSIONS` without updating `_LABEL_TO_SNAKE` AND every reviewer YAML rubric | §6.11 + ralph-70 | Parse silently drops unknown dimensions (`_normalize_dimension` returns None with no log). Add-without-mapping = score appears in reviewer text but never persists or triggers regression detection |
| **AP62** | Mixing the 0-10 evaluator scale with the 0-100 score_trajectory scale | §6.11 + ralph-70 | Two scales coexist deliberately: `runtime/evaluator.py` floats 0-10 per rubric dimension, `runtime/score_trajectory.py` ints 0-100 from peer-review text. Loop converting between MUST use explicit `*10`/`/10` with rounding semantics or it silently corrupts trajectory comparisons |
| **AP63** | Changing `check_early_stop` semantics to allow empty-deltas True | §6.11 + ralph-70 | Empty deltas means "no comparison was possible" (cold start), NOT "scores converged". Loop returning True on empty deltas would emit false-convergence signals on round 1, short-circuiting the revision loop entirely |
| **AP64** | Making `has_p0` positional in `check_early_stop` | §6.11 + ralph-70 | Keyword-only by signature; call sites pass `has_p0=True`. Positional change breaks every caller silently (third positional arg becomes a falsy bool/int) |
| **AP65** | Logging a warning when `_normalize_dimension` returns None | §6.11 + ralph-70 | Drop is intentional — reviewer text often contains analyses of unrelated dimensions ("readability", "tone") that are NOT pipeline-tracked. Warning every drop floods logs. If a specific drop is suspicious, add it to `_LABEL_TO_SNAKE` instead |
| **AP66** | Adding monkey-patch to a provider SDK without `__keepalive_patched__` re-entrancy guard | §6.13 + ralph-71 | `observability.py:82` checks `getattr(__init__, '__keepalive_patched__', False)` before patching. Without the guard, hot-reload / module-reimport double-wraps `__init__` and recurses, corrupting all subsequent agent constructions |
| **AP67** | Constructing per-agent `httpx.AsyncClient` instances (bypassing `_SHARED_KEEPALIVE_CLIENT`) | §6.13 + ralph-71 | The shared singleton at `observability.py:14` is the SINGLE connection pool across all 38+ agents. Per-agent clients = 38 separate pools = 38× more file descriptors AND no socket reuse — defeats the whole keepalive design |
| **AP68** | Calling `DBOS.launch()` BEFORE all DBOSAgent instances are registered | §6.13 + ralph-71 | Verified `observability.py:140-143` docstring: launch must be deferred until after agent registration or DBOS misses agents from its workflow registry. Two-step `init_dbos()` → register → `launch_dbos()` ordering is mandatory |
| **AP69** | Removing `_cancel_stale_workflows()` from `init_dbos()` | §6.13 + ralph-71 | Without the cancel pass, crashed PENDING workflows from a previous run cause `DBOS.launch()` to BLOCK FOREVER trying to recover them. SQLite UPDATE is idempotent and cheap — keep it |
| **AP70** | Renaming `runtime/parsing.py` `check_dialogue_health` "any 3 in window" instead of "3 consecutive" | §6.13 + ralph-71 | Reviewer / Devil's-Advocate dialogues legitimately contain spread-out agreement on different points. The CONSECUTIVE invariant catches actual sycophancy (3 turns in a row with no challenge), not normal back-and-forth |
| **AP71** | Changing `_CONFLICT_AVOIDANCE_PATTERNS` matching from AND to OR | §6.13 + ralph-71 | The strict AND (all 3 of "no critical issues" + "no major issues" + "no minor issues" in SAME message) is the signature of a sycophantic "all clear at every level" output. OR matching would flag every legitimate "no critical issues found" finding, drowning real signal |
| **AP72** | Adding a new consumer of `state.revision_context` outside `build_context` | §6.13 + ralph-72 | `build_context` is the SINGLE consumer that clears `state.revision_context = None` after applying. Adding another consumer either: (a) fires duplicate REVISION INSTRUCTIONS, or (b) reads stale revision context from a prior round. If a node needs revision data, read it via `build_context(state, ..., node_name=...)`, not directly |
| **AP73** | Reordering the `extract_field_text` dispatch tower | §6.13 + ralph-72 | Order is: falsy → BaseModel → dict (with `["raw"]` short-circuit) → list → str fallback. Many state dicts wrap raw LLM text under `"raw"` for round-tripping; checking dict before BaseModel would mis-handle `BaseModel` subclasses with dict-like attrs. Loop must keep this order |
| **AP74** | Replacing `ensure_ascii=False` in `json.dumps` calls | §6.13 + ralph-72 | Pipeline outputs Greek/math/Unicode (e.g. ⟨num:label⟩, ρ, α). `ensure_ascii=True` (default) escapes them as `⟨...` corrupting downstream parsers and trace tokens specifically (the `⟨` U+27E8 lookup fails). Always pass `ensure_ascii=False` when dumping pipeline data |
| **AP75** | Passing a dict / duck-typed object to `build_curated_context` | §6.13 + ralph-72 | Strict `isinstance(spec, ContextSpec)` check raises TypeError. Loop creating "convenience wrappers" that inline a dict would crash at first per-agent rollout call site |
| **AP76** | Treating `spec.allowed_numerical_labels == "all"` as iterable | §6.13 + ralph-72 | `"all"` is a sentinel STRING (Literal["all"]). Iterating it yields characters `'a'`, `'l'`, `'l'`. Loop MUST check the sentinel value FIRST, then treat the list/iterable case |
| **AP77** | Adding a UNIQUE constraint to `snapshots(run_id, snapshot_id)` | §6.9 + ralph-73 | The Python-level dedup in `snapshot_node_if_new` predates the schema and assumes NO unique constraint. Adding one breaks idempotent retries with `IntegrityError` on duplicate INSERT. Either keep the Python-level dedup OR add UNIQUE + change `INSERT` → `INSERT OR IGNORE` together |
| **AP78** | Removing the `_reset_crashed_sync` graceful TypeAdapter fallback | §6.9 + ralph-73 | Lines 352-370 patch `data_json` directly via JSON manipulation when `_snapshots_type_adapter` is None. This is the LEGITIMATE resume-time path — `reset_crashed_snapshots()` is called BEFORE `graph.iter_from_persistence` calls `set_types`. Removing crashes every resume |
| **AP79** | Resetting only `'running'` (not `'error'`) snapshots in `_reset_crashed_sync` | §6.9 + ralph-73 | Verified line 335: SQL filter is `status IN ('running', 'error')` — both reset. Single-status filter would leave error-status snapshots stuck and short-circuit resume on first retryable failure |
| **AP80** | Changing SQLite journal mode from WAL | §6.9 + ralph-73 | `PRAGMA journal_mode=WAL` enables concurrent reads (watchdog) + writes (pipeline). Default DELETE mode locks the DB during writes. Loop changing without watchdog awareness creates deadlocks |
| **AP81** | Collapsing `pipeline_state` table into `snapshots` | §6.9 + ralph-73 | Two-table design is intentional: pipeline_state mutates between nodes (UPSERT semantics), snapshots are append-only graph history. Collapsing forces every PipelineState mutation through snapshot-create overhead AND breaks the `record_run` async context manager invariant |
| **AP82** | Per-row TypeAdapter validation instead of `_load_all_sync` batch-join | §6.9 + ralph-73 | `build_snapshot_list_type_adapter` is a LIST adapter — there's no per-item adapter exposed by pydantic-graph. Loop "improving" by per-row validation crashes with TypeAdapter API errors |
| **AP83** | Persistent SQLite connection without `check_same_thread=False` + serialization | §6.9 + ralph-73 | Connection-per-call pattern is the safe default. Long-lived connection requires `check_same_thread=False` + asyncio.Lock or thread-safe pool. Loop introducing without considering thread safety = silent corruption under load |
| **AP84** | Using `runtime/throttle.py` for non-PydanticAI throttling (e.g. file writes, dashboard refresh) | §6.13 + ralph-74 | `throttle_hooks` is a `pydantic_ai.capabilities.hooks.Hooks` instance for `before_model_request`. Wrong API surface entirely for file-writes/HTTP-rate-limiting. Loop wanting time-based debounce of file writes MUST add a separate small utility next to the consumer (e.g. inline in `runtime/dashboard.py`), not extend throttle.py |
| **AP85** | Using `time.sleep` instead of `asyncio.sleep` in the throttle hook | §6.13 + ralph-74 | `time.sleep` blocks the event loop — defeats the entire async architecture. Pipeline becomes serial, watchdog can't write events.jsonl, dashboard freezes, recovery layers all fail simultaneously |
| **AP86** | Caching `tool_call_delay_seconds` at module load instead of fetching fresh per call | §6.13 + ralph-74 | Verified `throttle.py:39`: `delay = DEFAULT_CONFIG.tool_call_delay_seconds` is in the hook body (per-call lookup). Caching at module load breaks runtime config mutation (e.g. tests that lower delay to 0 between cases) |
| **AP87** | Catching only `Exception` (not `BaseException`) in `run_error` hook | §6.13 + ralph-74 | Hook signature is `error: BaseException` deliberately — KeyboardInterrupt + SystemExit + asyncio.CancelledError need centralized log lines too for clean-shutdown forensics. Narrowing to Exception loses these |
| **AP88** | Returning instead of raising in error hooks (`run_error`, `model_request_error`) | §6.13 + ralph-74 | These are observability hooks, NOT error-recovery hooks. They MUST `raise error` after logging or PydanticAI's retry/abort logic short-circuits and the agent silently succeeds with stale state. The `# type: ignore[return-type]` comments document this design |
| **AP89** | Replacing module-level singleton `throttle_hooks` with per-agent instances | §6.13 + ralph-74 | The shared `call_count` is intentional — first agent in pipeline gets the no-throttle freebie, every subsequent call across all 38+ agents gets the configured delay. Per-agent singletons would give each agent its own freebie call, multiplying burst rate by 38× and triggering Anthropic 429s |
| **AP90** | Adding a flag to `cli.py::run` without forwarding to `cli.py::supervised_run_cmd` | §13.6 + ralph-75 | `supervised_run_cmd` builds args list manually (line 388-392); only forwards `--force-experiment` and `--copilot`. Loop adding `--new-flag` to `run` must ALSO add `if new_flag: args.append("--new-flag")` in supervised_run_cmd or the supervised path silently drops it |
| **AP91** | Updating SQLite snapshot `status` column without also updating embedded `data_json["status"]` | §13.6 + ralph-75 | pydantic-graph reads via TypeAdapter from `data_json` blob, NOT from the column. Column-only update is SILENTLY IGNORED on resume. Verified `cli.py:531-550` `_set_status_created` updates BOTH. Same gotcha as `persistence.py::_rewrite_data_json` (AP-equivalent invariant) |
| **AP92** | Adding new top-level imports to `cli.py` instead of lazy-importing inside command handlers | §13.6 + ralph-75 | Heavy imports (sdk.Pipeline, models.*, recovery.supervisor) are deliberately deferred to inside `_make_pipeline` / `_init` / handlers so `--help` is fast. Adding to top of file regresses startup time for every CLI invocation |
| **AP93** | Calling `persistence._load_pipeline_state_sync` instead of going through async public API | §13.6 + ralph-75 | `cli.py::resume:253` already does this hack — bypasses asyncio for one call. Loop adding more callers entrenches the bypass. v2.6.0 candidate to expose `await persistence.load_pipeline_state(thread_id)` and migrate the resume command |
| **AP94** | Diverging CLI default and `WatchdogConfig` default for the same parameter | §13.6 + ralph-75 | Verified mismatch: CLI `watchdog --poll 15` vs `WatchdogConfig.poll_interval_s=30`. Loop "fixing" CLI defaults MUST sync with the API constructor defaults or programmatic vs CLI behavior diverges silently |
| **AP95** | Documenting CLI commands in CLAUDE.md without registering them in `cli.py` | §13.6 + ralph-75 | Verified: CLAUDE.md lines 64-68 document `research`/`write`/`review` phase commands but `cli.py` has no such `@app.command` decorators. Either add the commands OR strip from docs. Loop adding doc lines for new commands must verify they're decorated |

### How to use this catalog

The loop, before merging any delta:
1. Open this catalog. Skim every AP row.
2. For each AP row, ask "does my diff trigger this?" If yes, fix or surface.
3. Add new AP rows when discovering new anti-patterns mid-implementation.

Anti-pattern detection is cheap; anti-pattern aftermath (data loss, broken consumers, silent regressions) is expensive.

### Severity tagging (optional future work)

Not all anti-patterns are equal. Some cause silent failures (AP21, AP25), some cause data loss (AP30, AP41), some cause merge churn (AP14). A future iteration could tag each AP with severity. For now, treat all as blocking until proven otherwise.

---

## 29. Open Questions Tracker

Items the loop must NOT silently decide. Each row has a default to use if Jackson hasn't answered, plus the trigger for when the question must be resolved.

| OQ | Question | Default if unanswered | Resolution trigger | Owning component |
|---|---|---|---|---|
| OQ1 | What does `.github/workflows/publish.yml` actually do today? | Audit before tagging anything; assume "unknown, do not tag" | Before any v2.5.0-rc tag | §6.14.T2 |
| OQ2 | Does `pydantic-ai-slim[mcp]` extra need to stay? | Remove (per `project_pipeline_arch` memory: no MCP); confirm no transitive consumer via `uv tree` | Before §6.12.T7 ships | §6.12.T7 |
| OQ3 | Should `pydantic-ai-slim[exa]` ExaToolset replace direct Exa calls? | No for v2.5.0 (out of scope); revisit v2.6.0 | Post-v2.5.0 retro | §13.4 (Q2) |
| OQ4 | React dashboard v2 — ship in v2.5.0 or defer? | Defer if it becomes blocking; non-blocking otherwise (per §6.8.T5 deferred) | Phase 5 mid-point | §6.8.T5 |
| OQ5 | ~~What is the exact name of the ethics-checklist config flag?~~ **RESOLVED 2026-05-06 (ralph-17)** — `ethics_checklist_enabled` per `docs/superpowers/specs/2026-05-03-checklist-ethics-design.md:148`. (PRD ralph-1..16 incorrectly used `checklist_ethics_enabled` — fixed in 4 places.) | n/a | resolved | §6.5 |
| OQ6 | How are the 3 spot-review papers randomly selected? | Random `output/<run-id>/` from latest 10 successful runs (use `ls -t \| head -10 \| shuf -n 3`) | Before §6.15.T10 template ships | §6.15.T10 |
| OQ7 | Should DOI gate fail-open if CrossRef API is down? | Fail-closed by default; `--allow-unverified-dois` escape hatch (per R17) | §6.7.T2 implementation | §6.7 |
| OQ8 | Should examples/ scripts be runnable in CI? | Dry-run mode in CI per §6.12.T3; full run only in `make test-large` | §6.12.T3 implementation | §6.12 |
| OQ9 | Does StructureArchitect's "thesis-advancing role" requirement apply only to body sections, or also abstract/conclusion? | Body sections only (Intro, Methods, Results, Discussion). Abstract + Conclusion exempt — they're summaries by definition | §6.3.T3 implementation | §6.3 |
| OQ10 | What happens when cascade Stage A runs on a paper with zero numerical claims (no experiment)? | PASS-vacuous (no claims to validate). Distinct from "claims present but not tokenized" which FAILS. Documented in §6.4.T4 | §6.4.T3/T4 implementation | §6.4 |
| OQ11 | If `EthicsChecklistNode` finds 0 of 12 items applicable to a topic, does it pass? | PASS with `items_na = 12` and a warning. Surface in events.jsonl with `error_code: null`. Jackson decides if any topic class hits this in practice | §6.5.T1 implementation | §6.5 |
| OQ12 | Does `independent_verifier` consume the new `Thesis` and `CascadeResult` artifacts as required input or optional? | Required when respective flags on; optional fallback when off. Add to its YAML's input contract | §6.11.T5 implementation | §6.11 |
| OQ13 | What's the `authors.yaml` required schema? | At minimum: `[{name, affiliation, email, orcid?}]` per author. Validated by Pydantic in §6.7.T3 | §6.7.T3 implementation | §6.7 |
| OQ14 | Does §6.2.T7 (delete `tcp_server.py` + Dockerfile entry) require rebuilding the experiment Docker image? | Yes — `make docker-build` after merge. Document in CHANGELOG migration steps | §6.2.T7 implementation | §6.2 |
| OQ15 | How many sections does a "typical" v2.5.0 manuscript have? | 8 (IMRaD: Title + Abstract + Intro + Methods + Results + Discussion + Conclusion + References). Sysrev: same minus Methods + Results, plus Synthesis | §6.15.T3 (page count assertion sizing) | §6.15 |
| OQ16 | Is `target_journal: "Journal of Biomedical Informatics"` (existing default in `config.py`) the actual target? | Use as default; Jackson confirms per-paper via `--target-journal` CLI flag (already exists?) | Before personality reviewers fire on a real run | §6.4 (Spec 5) |
| OQ17 | Does the loop need to handle pre-v2.4.0 state files or only pre-v2.5.0? | Only pre-v2.5.0. v2.4.0 already required deleting pre-v2.4.0 state files (CHANGELOG note). v2.5.0 cleanup script targets v2.4.0 → v2.5.0 only | §6.9.T5 implementation | §6.9 |
| OQ18 | What's the Logfire project name post-v2.5.0? | Stays `research-demo` unless Jackson says otherwise. New project would orphan all historical traces | Pre-v2.5.0 tag | §6.13 |
| OQ19 | Does the weekly `make realign` cron require a hosted scheduler, or is it manual? | Manual for v2.5.0; `crontab` example in `docs/architecture/evaluation.md`; hosted scheduler is v2.6.0+ | §6.15.T12 implementation | §6.15 |
| OQ20 | When the loop hits an OQ during implementation, should it block or proceed with the default? | Proceed with the default + add a `// TODO: confirmed default for OQN` comment in the implementation. Surface to Jackson at next sync. Do not silently bypass | global directive | n/a |

### How to use this section

When the loop encounters a TBD or implicit assumption mid-implementation:
1. Check this list. If the question is here, use the listed default.
2. Add the comment `// TODO: OQN — confirmed default per PRD §29` at the relevant code location.
3. If the question is NOT here, add a new OQ row in the same PR with a proposed default and rationale.

This converts the "I assumed X" trap into "I used the documented default X, here's how to override it."

### Resolution log

Once Jackson confirms or overrides a default, append the resolution date and the chosen answer. Do not delete the row — the resolution history is itself documentation.

| OQ | Resolved | Date | Resolution |
|---|---|---|---|
| OQ5 | yes | 2026-05-06 (ralph-17) | Flag is `ethics_checklist_enabled` per Spec 8 design doc. PRD initially had `checklist_ethics_enabled`; consistency sweep fixed 4 occurrences (lines 463, 1533, 2037, 2777). |
| OQ-NEW-1 | yes | 2026-05-06 (ralph-18) | `ResearchState` field for development chain is `chain` not `development_chain` (verified `research/state.py:42`); for thesis is `thesis` not `thesis_statement` (verified `research/state.py:43`). §16 rows 1-2 fixed; §16 naming-correction table extended. |
| OQ-NEW-2 | yes | 2026-05-06 (ralph-18) | Class is `NoveltyReport` not `PointWiseNoveltyReport` (no such class; verified `models/novelty_report.py:78`). State field is `ReviewState.novelty_report` not `pointwise_novelty_report` (verified `review/state.py:43`). §16 row 5 fixed. |
| OQ-NEW-3 | yes | 2026-05-06 (ralph-19) | `ExperimentState.scored_designs` does not exist; actual fields are `selected_designs` (`SelectedDesigns`) and `design_comparison` (`DesignComparison`). `DesignBundle` is the bundle wrapper class. All 3 verified in `experiment/state.py:55-57`. §16 row 11 fixed. |
| OQ-NEW-4 | partially | 2026-05-06 (ralph-19) | `IntegrityState.ethics_checklist` does NOT exist at HEAD (verified). Phase 2 wiring §6.5.T1 must ADD this field. §16 row 8 updated to mark "TO BE ADDED in §6.5.T1". |
| OQ-NEW-5 | yes | 2026-05-06 (ralph-19) | Trace token resolution lives at `WritingState.numerical_store: NumericalStore` (verified `writing/state.py` — populated by `AnalysisNode` upstream per inline doc), not just a JSON file. Class is `NumericalStore` with `NumericalProduct[]` per `models/numerical.py:29`. §16 row 9 fixed. |
| OQ-NEW-6 | yes | 2026-05-06 (ralph-21) | `PipelineState` mirrors most subgraph state fields after the subgraph completes (verified `pipeline/state.py`). §16 added a "Dual-layer state caveat" subsection listing 8 verified mirrored fields. Phase 2 artifacts must be added to BOTH layers. |
| OQ-NEW-7 | yes | 2026-05-06 (ralph-21) | `copilot_comments: dict[str, str]` is a top-level `PipelineState` field for §6.10 copilot checkpoints (`post_intake`, `post_experiment_design`, `post_first_draft`). Was missing from §16; added as row 16 with `copilot_enabled` gating flag. |
| OQ-NEW-8 | yes | 2026-05-06 (ralph-22) | `make test-medium` Makefile target does NOT exist. The CI job named `test-medium` (per §22.3) invokes `make test-integration` which IS the medium-tier Makefile target (verified `Makefile:53`). §22.3 row updated to clarify. |
| OQ-NEW-9 | yes | 2026-05-06 (ralph-22) | conftest.py provides 4 TestModel helpers, not just 1: `make_test_model`, `make_structured_test_model` (PromptedOutput), `make_union_test_model` (union types), `make_field_overrides_test_model` (partial overrides). All 4 verified at `tests/conftest.py:33-105`. §13.1 expanded to list all 4. Loop should pick the right helper for the agent's output_type. |
| OQ-NEW-10 | partial | 2026-05-06 (ralph-24) | `defusedxml>=0.7.1` declared at `pyproject.toml:34` but ZERO usages in `src/` (verified). Either transitive consumer or stale. §6.12.T7 extended to include investigation. |
| OQ-NEW-11 | partial | 2026-05-06 (ralph-24) | Type-checker inconsistency: Makefile uses `npx basedpyright`, pyproject pins `pyright>=1.1`, CI uses `uv run pyright`. New §6.14.T7 added to resolve. |
| OQ-NEW-12 | partial | 2026-05-06 (ralph-24) | mkdocs deps declared but no `mkdocs.yml` exists. Consistent with §6.12.T9 "out of scope" but undocumented. New §6.14.T9 added to either keep+document or remove. |
| OQ-NEW-13 | partial | 2026-05-06 (ralph-24) | `pip-audit` and `bandit` security scanners declared as dev deps but not run in CI. New §6.14.T8 added to wire both as per-PR jobs. |
| OQ-NEW-14 | yes | 2026-05-06 (ralph-25) | All 50 agent registry keys verified across 5 subgraphs (research 12, review 12, writing 13, experiment 11, integrity 2). All match PRD references. One subtle clarification: writing/agents.py has `"visualization"` as registry key + `visualization.yaml` + `name: visualization_agent` even though the role was renamed to "figure curator" in commit `27755c7`. Loop must use `agents["visualization"]`, not `agents["figure_curator"]`. §6.3 current state row clarified inline. |
| OQ-NEW-15 | yes | 2026-05-06 (ralph-26) | Verified `pipeline/nodes.py` outer-graph node classes (14 total: IntakeNode, NoveltyGateNode, ResearchPhaseNode, WritePhaseNode, ExperimentClassifierNode, ExperimentPhaseNode, PreIntegrityNode, IntegrityFixNode, ReviewPhaseNode, FinalIntegrityNode, FinalIntegrityFixNode, FinalizeNode, SummaryNode, AbortNode). Drift found: PRD §5.1 referenced non-existent `ExperimentFixNode` — fixed inline (retry is inline, no separate fix node, counter on `PipelineState.experiment_fix_count`). |
| OQ-NEW-16 | yes | 2026-05-06 (ralph-26) | Verified `experiment/graph.py` has 9 node classes (not 7 as PRD §6.2 claimed). Drift bugs: PRD said `ExperimentDesignerNode` → actual is `ExperimentDesignNode` (no -er-); `ExperimentDesignerBundleNode` → actual is `ExperimentDesignBundleNode`. Asymmetry: agent registry KEYS use -er- (`experiment_designer`, `experiment_designer_bundle`), node CLASSES don't. `ImprovementNode` + `MultiSeedNode` do NOT exist as separate classes — improvement loop is inline (uses `experiment_improver` agent yaml); multi-seed replication is inline. §6.2 current state fixed. |
| OQ-NEW-17 | yes | 2026-05-06 (ralph-27) | Real production `events.jsonl` has 3 watchdog event types NOT documented in §18.2: `watchdog_killing`, `watchdog_killed`, `watchdog_resuming` (verified at `output/run-0504-1802_ec44/events.jsonl`). Added all 3 to §18.2 with verified field shapes. Added caveat to §6.6.T2 design: the new generic `recovery_event` type should COEXIST with the 3 specific watchdog types (option a) rather than replace them, to preserve backward-compat for any Logfire saved searches / scripts that grep specific names. |
| OQ-NEW-18 | yes | 2026-05-06 (ralph-28) | Dashboard whitelist (`runtime/dashboard.py:213-216`) supports 2 MORE watchdog types not seen in production samples but supported by renderer: `watchdog_resumed` (success of resume) + `watchdog_aborted` (3-strikes abort). Complete watchdog event-type set is 5: killing, killed, resuming, resumed, aborted. Added to §18.2. |
| OQ-NEW-19 | yes | 2026-05-06 (ralph-28) | Verified `pipeline_status` enum at `runtime/dashboard.py:83`: `"pending" \| "running" \| "completed" \| "error" \| "watchdog_aborted"` (5 values). Documented in §18.2 for consumer code. |
| OQ-NEW-20 | yes | 2026-05-06 (ralph-29) | Stage enum value for writing is `"write"` NOT `"writing"` (verified `core/enums.py:12` + production events.jsonl `stage_change` records). Confusing because subgraph folder is `writing/` and AgentType value is `"writing"`. Documented in new §18.6 + new "Stage value vs subgraph folder name" subsection. |
| OQ-NEW-21 | yes | 2026-05-06 (ralph-29) | `Verdict.PASS_WITH_NOTES` does NOT exist; correct value is `Verdict.PASS_WITH_CONDITIONS` (verified `core/enums.py:62-67`). PRD §6.1 contract fixed. |
| OQ-NEW-22 | yes | 2026-05-06 (ralph-29) | `EditorialDecision` values are Title Case with internal spaces: `"Accept"`, `"Minor Revision"`, `"Major Revision"`, `"Reject"` (verified `core/enums.py:73-76`). PRD prose said "accept \| revise \| reject" lowercase. `EditorialDecision.from_label()` provides case-insensitive parse. Documented in §18.6. |
| OQ-NEW-23 | yes | 2026-05-06 (ralph-29) | TWO different status concepts in the codebase: `PipelineStatus` enum (6 values, `core/enums.py:21`) vs dashboard `pipeline_status` field (5 string-literals, `runtime/dashboard.py:83`). They look similar but mean different things. Dashboard's `"watchdog_aborted"` ≠ `PipelineStatus.ABORTED.value = "aborted"`. Documented in new §18.6 "Two status concepts" subsection — recommend rename in future cleanup. |
| OQ-NEW-24 | yes | 2026-05-06 (ralph-31) | **Cascade has 4 stages, not 3.** Spec 6 design doc (`docs/superpowers/specs/2026-05-03-cascaded-reviewer-design.md`) verifies: Stage A (NUMERICAL_GROUNDING), B (NOVELTY), C (METHODOLOGY), **D (NARRATIVE)**. PRD §6.4 prose mentioned only A/B/C. CascadeResult always has 4 entries (SKIPPED for unreached). §16 row 6 fixed to list all 4 stages; §17 CAS namespace gained CAS006 StageDNarrativeWeak. |
| OQ-NEW-25 | yes | 2026-05-06 (ralph-31) | `StageVerdict` enum has 4 values (`pass`, `short_circuit_reject`, `skipped`, `not_run`), NOT pass/fail. §18.2 cascade_verdict event schema fixed to use the 4-value enum + clarified Stage D doesn't short-circuit (it's the leaf). |
| OQ-NEW-26 | yes | 2026-05-06 (ralph-32) | **Trace token notation drift**: PRD said `{{trace:expr_id}}` (4 places). Actual notation is `⟨num:label⟩` (Unicode angle brackets U+27E8 / U+27E9 + `num:` prefix + Python identifier label) per `traceability/_patterns.py:11` regex `r"⟨num:(?P<label>[a-zA-Z_][a-zA-Z0-9_]*)⟩"`. Fixed all 4 occurrences. Glossary updated with the verified pattern + character codepoints to prevent ASCII-bracket confusion. |
| OQ-NEW-27 | yes | 2026-05-06 (ralph-32) | Spec 4 design doc verifies: NoveltyReport overall verdict is `REJECT_NOVELTY` when ANY claim is `redundant`; `partial_overlap` is a warning (Non-goal #3), not a rejection. ClaimVerdict has 3 values; ClaimNoveltyDimension has 5 values. §16 row 5 expanded with all of this. |
| OQ-NEW-28 | yes | 2026-05-06 (ralph-33) | Spec 1 design doc verifies hedge-vs-aborting phrase distinction. Hedges (`"approximately"`, `"around"`, `"roughly"`, `"circa"`, `"~"`) trigger ModelRetry (TRC001); aborting phrases (`"[insert"`, `"[unknown"`, `"[to be determined"`, `"subject to revision"`) trigger fail-loud (TRC002, no retry). Hedge proximity is **5 tokens BEFORE** the `⟨num:label⟩` (direction matters); configurable via `HEDGE_PROXIMITY_TOKENS` (verified `validators.py:35`). §6.11.T2 expanded with both lists + direction. |
| OQ-NEW-29 | yes | 2026-05-06 (ralph-33) | Spec 1 LaTeX target naming convention codified: substitution replaces `⟨num:label⟩` with `\hyperlink{num_<label>}{<value>}`; Notes appendix has `\hypertarget{num_<label>}{}` per entry; Code appendix has `\hypertarget{code_<run>_<line>}{}` at producing lines. §16 row 9 expanded with the convention + 9-field `NumericalProduct` schema. |
| OQ-NEW-30 | yes | 2026-05-06 (ralph-34) | Spec 5 design doc has internal inconsistency: claims persona reviewers replace `peer_reviewer`, but `peer_reviewer` lives in `writing/agents.py` (writing-phase pre-pass), not in `review/agents.py`. The actual review-subgraph legacy trio is `domain_reviewer` + `methodology_reviewer` + `perspective_reviewer` (verified ralph-25). Corrected mapping: `senior_gatekeeper_reviewer` → `perspective_reviewer`; `applied_practitioner_reviewer` → `domain_reviewer`; `methodology_purist_reviewer` → `methodology_reviewer`. §6.4.T2 expanded with the corrected mapping + spec-doc inconsistency note. |
| OQ-NEW-31 | yes | 2026-05-06 (ralph-34) | Spec 5 PersonaSpec has 3 axes with full enum coverage: `Commitment` (2 values: thorough, superficial); `Intention` (4 values: skeptical_gatekeeper, applied_practitioner, enthusiastic_advocate, domain_purist); `Knowledgeability` (3 values: deep_in_field, adjacent_field, novice). Total combinations = 24, but v2.5.0 wires only 3. §16 row 4 expanded with all enums + the "3 of 24 combinations" note for future expansion. |
| OQ-NEW-32 | yes | 2026-05-06 (ralph-35) | Spec 8 design doc verifies the 12 EthicsChecklist standard item names (verbatim snake_case) — PRD said "12 items" abstractly. §16 row 8 + §6.5.T2 expanded with the full item list. Plus `overall_verdict` enum has 3 values (`pass` / `pass_with_waivers` / `block`) and `blocker_items: list[str]` carries blocking item names. |
| OQ-NEW-33 | yes | 2026-05-06 (ralph-35) | Spec 8 requires NEW agent yaml at `integrity/specs/ethics_reviewer.yaml` (note: name is `ethics_reviewer` with -er suffix, NOT `ethics_review`). Was missing from §15 §6.5 Create column — added. Output type is `PromptedOutput[EthicsChecklist]`. Source-verification artifacts must be injected into agent context (this is what surfaces structural COI patterns). §6.5.T1 description expanded. |
| OQ-NEW-34 | yes | 2026-05-06 (ralph-36) | NoveltyVerdict enum has 3 values: `"novel"` / `"partial"` / `"redundant"` (verified `research/novelty_gate.py:130`). PRD §18.2 used `"soft_warn"` — wrong term. Fixed novelty_gate_verdict event schema with full NeighborPaper field set + differentiation_paragraph field. |
| OQ-NEW-35 | partial | 2026-05-06 (ralph-36) | Design ambiguity in §6.1.T5: Spec 3 design doc says "generate differentiation_paragraph via new agent" on PARTIAL verdict; PRD said "trigger ResearchQuestionNode iteration with hint". TWO different mechanisms — Jackson must decide. §6.1.T5 expanded with both options + recommendation (option a per spec). NOT YET RESOLVED. |
| OQ-NEW-36 | yes | 2026-05-06 (ralph-37) | Spec 2 design doc verifies: ONE `ChainOfIdeasNode` calling TWO agents (`chain_of_ideas_extractor` + `thesis_extractor`), NOT two separate node classes. PRD ralph-1..36 incorrectly implied two nodes. §6.1.T2 + §16 rows 1-2 corrected. |
| OQ-NEW-37 | yes | 2026-05-06 (ralph-37) | Spec 2 enum + field enumeration: `MilestoneType` has 5 values (concept_intro / method_ext / benchmark / refutation / application); `EdgeRelation` has 4 values (extends / refutes / supersedes / applies_to); `DevelopmentChain` has `terminal_unsolved_problem: str` field that drives the thesis (not just milestones+edges); `ThesisStatement.novelty_dimension` Literal has 4 values (`new_concept` / `method_extension` / `new_application` / `refutation`). §16 rows 1-2 expanded with full schemas. |
| OQ-NEW-38 | yes | 2026-05-06 (ralph-37) | TWO different "novelty dimension" enums in the codebase: `ThesisStatement.novelty_dimension` Literal (4 values: new_concept / method_extension / new_application / refutation) per Spec 2; `ClaimNoveltyDimension` enum (5 values: new_concept / new_method / new_application / new_dataset / new_result) per Spec 4. They overlap on `new_concept` and `new_application` but diverge elsewhere. Loop must use the right one for the right context (thesis = Spec 2; per-claim = Spec 4). Documented inline in §16 row 2. |
| OQ-NEW-39 | yes | 2026-05-06 (ralph-38) | Spec 7 has 4 Pydantic models, not 3: `DesignBundle`, `DesignScore` (was missing from §16), `SelectedDesigns`, `DesignComparison`. `DesignScore` carries the 5-criterion rubric (data_availability / methodological_fit / expected_discriminative_power / risk / overall) that `design_scorer` agent emits per design. §16 row 11 expanded with all 4 schemas. |
| OQ-NEW-40 | yes | 2026-05-06 (ralph-38) | Spec 7's `DesignComparison.discussion_paragraph` is auto-inserted into paper's Discussion section by §6.3 DraftWriter — important hand-off detail. Reviewers will read it for "did you consider X alternative?" challenges. §6.2.T6 expanded to capture this writer hand-off requirement. |
| OQ-NEW-41 | yes | 2026-05-06 (ralph-38) | Spec 7 design says rename `ExperimentDesignNode` → `ExperimentDesignBundleNode`. Actual codebase (per iter 26 verification) has BOTH coexisting: `ExperimentDesignNode` for single-design path, `ExperimentDesignBundleNode` for breadth path. Implementation chose to coexist rather than replace (likely for `legacy_single_design` escape hatch). §16 row 11 clarified. |
| OQ-NEW-42 | yes | 2026-05-06 (ralph-39) | `MaterialPassport` is a real model in `models/integrity.py:245` (7 fields + 2 properties: `is_stale` checks `PASSPORT_FRESHNESS_HOURS=24` window, `can_skip_pre_review_integrity` returns True if VERIFIED+fresh). Used at `PipelineState.material_passport` for skip-pre-integrity optimization. Was completely undocumented in PRD. Added as §16 row 17. |
| OQ-NEW-43 | yes | 2026-05-06 (ralph-39) | Integrity subgraph has **5-phase architecture** (PhaseA References, PhaseB CitationContext, PhaseC Data, PhaseD Originality, PhaseE Claims) producing PhaseResult/IssueCounts/IntegrityReport, NOT just "1 composite node" as PRD §6.5 said. `models/integrity.py` has 18+ classes for the integrity report structure. §6.5 current state corrected. |
| OQ-NEW-44 | yes | 2026-05-06 (ralph-39) | `VerificationStatus` is a Literal at `models/shared.py:85`: `"VERIFIED"` / `"UNVERIFIED"` / `"STALE"` (3 values). Default on MaterialPassport is `"UNVERIFIED"`. Constant `PASSPORT_FRESHNESS_HOURS=24` defines the staleness window. Documented in §16 row 17. |
| OQ-NEW-45 | yes | 2026-05-06 (ralph-40) | `tools/integrity_tools.py` has 3 distinct async functions, NOT 3 conflated capabilities of one tool. (1) `extract_claims` returns JSON with claim IDs `CLAIM-NNN` zero-padded + 4 claim types; (2) `check_plagiarism_heuristic` returns JSON with verdict `"REVIEW_NEEDED" \| "NO_FLAGS"`; (3) `detect_ai_style_indicators` is SEPARATE, not a sub-feature of plagiarism. All return JSON strings (legacy pattern, pre-dates `models/integrity.py`). §6.5 current state expanded. |
| OQ-NEW-46 | yes | 2026-05-06 (ralph-40) | §6.5.T4 refactor target made concrete: `detect_ai_style_indicators(text)→str` becomes `detect_ai_style_indicators(sections)→dict[section, AIStyleScore]` with new Pydantic model `AIStyleScore(score, reasons, revise_directive)`. Keep legacy JSON behind `legacy_ai_style_detection` flag for one release. |
| OQ-NEW-47 | yes | 2026-05-06 (ralph-41) | `throttle_hooks` is a **module-level singleton** at `runtime/throttle.py:76` — single counter shared across ALL agents in the process. For per-test isolation, use the factory `make_throttle_hooks()`. Three hook handlers (before_model_request / run_error / model_request_error). Throttle skips first call, applies 10s delay (default) starting from call #2. §13.1 row expanded with all of this. |
| OQ-NEW-48 | partial | 2026-05-06 (ralph-41) | **Stale docstring** at `runtime/throttle.py:1`: "Rate limit throttle hook for Vertex AI quota protection." Codebase uses Anthropic, not Vertex AI. Behavior is correct (throttles all model requests) but the comment is misleading. **Action**: fix docstring in a future iteration; surface to Jackson. |
| OQ-NEW-49 | yes | 2026-05-06 (ralph-42) | **Recursive-supervisor pattern**: a single user-visible `run_id` can span MULTIPLE supervisor processes across the recovery lifecycle (original supervisor exits on SIGKILL → watchdog auto-resumes → fresh supervisor + fresh watchdog spawned). Verified `recovery/supervisor.py:1-17` docstring. PRD §6.6 didn't capture; expanded. Critical for log-aggregation: never assume one supervisor process per run. |
| OQ-NEW-50 | yes | 2026-05-06 (ralph-42) | Verified supervisor constants: `_THREAD_ID_TIMEOUT_S = 60` (wait for pipeline first events.jsonl line); `_WATCHDOG_GRACEFUL_S = 10` (matches L4 watchdog 10s SIGTERM-before-SIGKILL window). `_strip_flag(args, *flags)` helper at `supervisor.py:38` normalizes argv before re-spawn (typer "last wins" workaround). All documented in §6.6 current state. |
| OQ-NEW-51 | yes | 2026-05-06 (ralph-43) | `tools/execution/sanity.py::sanity_check_results` enumerates **6 specific deterministic checks** with hardcoded thresholds — bounded-metric set is `{accuracy, f1, f1_macro, f1_weighted, roc_auc, precision, recall}` (7 metrics, loop must extend if breadth-mode adds new metrics); high-accuracy threshold is `acc > 0.99`; identical-methods detection at `len(metrics) >= 2`. Returns `list[str]` not Pydantic. §6.2 current state expanded with all 6 checks + 4 helper functions. |
| OQ-NEW-52 | partial | 2026-05-06 (ralph-43) | `sanity_check_results` returns `list[str]` not a typed Pydantic report. Refactor candidate for v2.6.0+ (typed `SanityReport(issues: list[SanityIssue])`). Out of v2.5.0 scope but recorded so loop doesn't drift further. |
| OQ-NEW-53 | yes | 2026-05-06 (ralph-44) | **Aggregation is MEDIAN for ≥3 evaluators, MIN for exactly 2** (conservative — pessimistic for small panels) per `evaluator.py:100-103`. PRD said "default threshold 7.0" but didn't specify aggregation algorithm. Critical when loop adds more evaluators (e.g., adding GPT-5 back as a second model would trigger min() not median). Documented in §6.11 current state. |
| OQ-NEW-54 | yes | 2026-05-06 (ralph-44) | **PASS requires BOTH** every-dimension-≥-threshold AND average-≥-threshold per `evaluator.py:38` system prompt. Not "PASS if average meets threshold". Loop must preserve this when extending rubric. Documented. |
| OQ-NEW-55 | yes | 2026-05-06 (ralph-44) | **Rubber-stamp warning** at `evaluator.py:107`: any single evaluator giving all scores ≥9.5 logs an anti-sycophancy warning. Important behavioral check the loop must preserve when modifying evaluator (e.g., the §6.11.T4 per-node thresholds work). Documented in §6.11. |
| OQ-NEW-56 | yes | 2026-05-06 (ralph-44) | Verdict literal is `"PASS"\|"NEEDS_IMPROVEMENT"` (verified `evaluator.py:116`), NOT pass/fail or PASS/FAIL. Distinct from `Verdict` enum in `core/enums.py` which has 6 different values. Two more "verdict" concepts in the codebase that look similar but aren't: `EvaluationResult.verdict` (2 values, evaluator output) vs `Verdict` enum (6 values, integrity output). Documented. |
| OQ-NEW-57 | yes | 2026-05-06 (ralph-45) | **Persistence class drift**: PRD said `FileStatePersistence` in 4 places (executive summary, §6.6, §6.9, §26 D23). Actual class is `SqliteStatePersistence` at `persistence.py:62`. No `FileStatePersistence` exists. Persistence is SQLite-backed (`.pipeline_runs/pipeline.sqlite`), not file-per-run JSON. State files in `.pipeline_runs/<thread_id>_*.json` are an additional artifact format separate from the SQLite snapshot store. Fixed all 4 occurrences via replace_all. |
| OQ-NEW-58 | yes | 2026-05-06 (ralph-45) | `Pipeline` constructor has 7 params (1 positional + 6 keyword-only): topic, thread_id, interactive, revision_instructions, persistence_dir, use_dbos, paper_config. Auto-thread-id format: `run-MMDD-HHMM_xxxx` (4-char hex suffix). DBOS opt-in via constructor (default off). `Pipeline.observe(callback)` confirmed NOT-yet-existing — §6.12.T2 net-new work. §6.12 current state expanded. |
| OQ-NEW-59 | partial | 2026-05-06 (ralph-46) | **What happens to `experiment/harness.py` after §6.2.T7 deletes InteractiveMLNode?** Three options Jackson must decide: (a) delete harness.py too — ConfigWriter only writes YAML post-Dagster, no executable surface; (b) port to ConfigWriter as defensive layer for any LLM-emitted YAML; (c) keep as defensive infrastructure for future tool-using agents. Recommendation: (a). §6.2.T7 expanded with both possibilities. NOT YET RESOLVED. |
| OQ-NEW-60 | yes | 2026-05-06 (ralph-46) | `experiment/harness.py` 5-layer enforcement architecture documented (PrepareTools / before_tool / after_tool ×2 / output_validator). 14 FORBIDDEN_IMPORTS frozenset + ALLOWED_SKLEARN (4 entries) + ALLOWED_AUTOGLUON (5 entries) + TEMPLATE_MAP (3 problem-types) all enumerated. Loop must extend FORBIDDEN_IMPORTS if blocking new ML libs and TEMPLATE_MAP if adding new problem types. §6.2 current state expanded. |
| OQ-NEW-61 | yes | 2026-05-06 (ralph-47) | **`IssueSeverity` collision**: TWO different types — `core/enums.py:95` StrEnum (4 lowercase values: critical/major/minor/suggestion) vs `models/shared.py:83` Literal (3 uppercase values: SERIOUS/MEDIUM/MINOR). Same name, different values, different cases. New §18.6.1 subsection added documenting the trap. Loop must use explicit imports. |
| OQ-NEW-62 | yes | 2026-05-06 (ralph-47) | **5th verdict-like type discovered**: `IntegrityVerdict` Literal at `models/shared.py:84` (3 values: PASS / PASS_WITH_CONDITIONS / FAIL). Distinct from the other 4 verdicts (`Verdict` 6, `StageVerdict` 4, `ClaimVerdict` 3, `EvaluationResult.verdict` 2). Added to §18.6 enum table. Total verdict-concept count now 5. |
| OQ-NEW-63 | yes | 2026-05-06 (ralph-47) | `StructureType` Literal has **6 values**, not "IMRaD vs sysrev" binary as PRD §6.3 prose implied. Values: IMRaD, literature_review, theoretical, case_study, policy_brief, conference. The §6.15 `imrad_completeness` judge only fires for `"IMRaD"` papers; other structure types have different completeness rubrics — important for §6.15 fixture diversity. Documented in §18.6. |
| OQ-NEW-64 | yes | 2026-05-06 (ralph-47) | Documented 13 Literal types in `models/shared.py` (writing/review/integrity sides): CitationFormat, StructureType, ArgumentStrength, ModifierStyle, WeaknessType, WeaknessSeverity, ConsensusLevel, ItemType, Priority, ResponseStatus, IssueSeverity (Literal — distinct from enum), IntegrityVerdict, VerificationStatus. Plus PASSPORT_FRESHNESS_HOURS=24 constant. §18.6 enum table extended. |
| OQ-NEW-65 | yes | 2026-05-06 (ralph-48) | `FINERScores` uses **3-5 score range**, NOT 0-10 like other rubrics in PRD §6.1. 5 dimensions (feasible/interesting/novel/ethical/relevant) + derived `average` property. Different scoring system from the per-node evaluator threshold (7.0/10). Loop must not conflate when computing aggregate research-question quality. |
| OQ-NEW-66 | yes | 2026-05-06 (ralph-48) | `RQBrief.sub_questions` Pydantic-constrained to `Field(min_length=2, max_length=5)`. `methodology_type` is Literal of 3 values: `qualitative` / `quantitative` / `mixed`. §16 row 2 (RQBrief implicit usage) + §6.1 contract should reflect both constraints. |
| OQ-NEW-67 | yes | 2026-05-06 (ralph-48) | **§6.1.T6 expanded**: must also delete `EthicsReviewOutput` Pydantic class at `models/research.py:395` (output type of the agent being deleted — orphan class if left). **§6.1.T7 expanded**: must also delete `KnowledgeGraph` (`:227`), `SourceRelationship` (`:204`), `ResearchCluster` (`:216`) — all 3 are KnowledgeGraph-specific output types that orphan when the node is gone. |
| OQ-NEW-68 | yes | 2026-05-06 (ralph-49) | `models/review.py` has 22 classes. `PeerReviewReport` (legacy 3 trio) and `PersonaReviewOutput` (Spec 5 replacement) both stay during legacy-flag transition. Field constraints: `confidence_score 1-5`, `strengths/weaknesses 1-5 items`, `summary_assessment 150-250 words`. `overall_recommendation: str` untyped — refactor opportunity to use `EditorialDecision` enum (out of v2.5.0 scope). §6.4 current state expanded. |
| OQ-NEW-69 | partial | 2026-05-06 (ralph-49) | Refactor opportunity: `PeerReviewReport.overall_recommendation: str` → `EditorialDecision` enum (Title-Case 4 values). Would catch typos at type-check time. Recorded for v2.6.0+ — not blocking v2.5.0. |
| OQ-NEW-70 | yes | 2026-05-06 (ralph-50) | `AgentMessageCache(cache_dir, agent_name)` API verified — 4 methods (save/load/clear/exists), file path `<cache_dir>/<agent_name>.json`, corrupt cache silently returns None (does NOT raise). Loop must understand: corrupt cache → fresh start, not crash. §6.9 current state expanded. |
| OQ-NEW-71 | partial | 2026-05-06 (ralph-50) | **§6.9.T2 reconsidered**: the proposed `for_agent(agent_name, thread_id)` factory is sugar over existing `AgentMessageCache(cache_dir, agent_name)` constructor. Three options: (a) classmethod sugar `AgentMessageCache.for_agent(thread_id, agent_name)`, (b) leave as-is, (c) full rename refactor. Recommendation: (a) — minimal API change. §6.9.T2 task description updated; full refactor de-scoped. |
| OQ-NEW-72 | yes | 2026-05-06 (ralph-51) | `Heartbeat` verified API: `Heartbeat(path, interval_s=30.0)` context manager. Daemon thread (NOT asyncio task — explicit reason cited at heartbeat.py:1-7: blocked event loop e.g. socket.recv in SDK). Atomic write via .tmp+rename. Thread name `pipeline-heartbeat-{path.name}`. Cites Prefect #21184/PR #21276 as precedent. §6.6 expanded. |
| OQ-NEW-73 | yes | 2026-05-06 (ralph-51) | `ProcessLock(persistence_dir, thread_id)` writes **2 files per run** (not 1): `<thread_id>.pid` + `<thread_id>.pgid`. Graceful fallback when `os.getpgid(0)` raises OSError: writes own PID as PGID, watchdog degrades to single-process kill (os.kill instead of os.killpg). Cleanup uses missing_ok=True. Atomic .tmp+rename throughout. §6.6 expanded. |
| OQ-NEW-74 | yes | 2026-05-06 (ralph-52) | L1 keepalive constants: `_KEEPIDLE_S=60` + `_KEEPINTVL_S=15` + `_KEEPCNT=4` → **detection ≈ 120s** before OS declares socket dead. Per-OS branching documented (macOS / Linux / Windows fallback). Background context (macOS default keepidle = 2 hours) and Prefect/mcp-stdio precedent cited. §6.6 expanded. |
| OQ-NEW-75 | yes | 2026-05-06 (ralph-52) | **CRITICAL SCOPE CLARIFICATION**: L2 `bounded_agent_run` does NOT catch stuck-in-recv stalls. PRD prose implied "L2 raises AgentTimeoutError on stall" — but `asyncio.wait_for` cannot preempt a sync syscall blocked in the kernel. Stuck-in-recv stalls are L1's (TCP keepalive) and L4's (watchdog) job. L2 only catches LEGITIMATE-slow LLM thinking. Loop must understand this division of responsibility — wiring L2 into more places does NOT add stall coverage. §6.6 L2 description corrected. |
| OQ-NEW-76 | yes | 2026-05-06 (ralph-53) | **`max_idle_s` default is 600 (10 min), NOT 75s** as PRD §6.6 said in 4 places. 75s was the original default but caused false-positive kills at age_s=76.6 in run-0504-1802_ec44; legitimate nodes (SourceVerificationNode looping S2/CrossRef/Retraction-Watch + BibliographyNode batching Exa) take 60-120s between events.jsonl writes. 600s gives comfortable headroom over slowest known node while still catching multi-hour wedges. Fixed all 4 PRD places. |
| OQ-NEW-77 | yes | 2026-05-06 (ralph-53) | **CRITICAL DESIGN DETAIL**: heartbeat.txt is NOT used for stall detection. PRD prose said watchdog polls "events.jsonl mtime + heartbeat.txt mtime" — wrong. Per `watchdog.py:9-15` docstring, heartbeat keeps ticking even when main code is hung in await (daemon thread). Trusting it masked the exact failure mode in run-0504-1212_cf0d (1h41m wedged with fresh heartbeat). Events.jsonl is the ONLY proof-of-progress signal. Heartbeat exists to prove daemon thread alive, NOT pipeline progressing. §6.6 L4 description corrected with explicit "loop must NOT add heartbeat to stall logic" warning. |
| OQ-NEW-78 | yes | 2026-05-06 (ralph-53) | Watchdog constants verified: `poll_interval_s=30`, `_GRACEFUL_KILL_S=10`, `_RESUME_PID_TIMEOUT_S=60`, `max_strikes=3`. All documented in §6.6. |
| OQ-NEW-79 | yes | 2026-05-06 (ralph-54) | `run_writer_reviewer_dialogue` already fully implemented at `traceability/dialogue.py`. §6.10.T1 task is just to call it from a new `SectionDialogueNode` in `writing/graph.py` — not implement the helper. **`DEFAULT_TERMINATION_PHRASE = "The section does not require any changes"`** (exact verbatim string). Loop must NOT change. §6.10.T1 expanded with full signature + termination phrase. |
| OQ-NEW-80 | yes | 2026-05-06 (ralph-54) | Copilot quantified benefit (data-to-paper): 2-3 single-sentence comments turn 90% error rate → 10-20% on complex tasks. Default stdin timeout 60s; whitespace-only treated as empty. `StdinReader` Type alias accepts both async + sync (test ergonomics). §16 row 16 expanded. |
| OQ-NEW-81 | yes | 2026-05-06 (ralph-55) | `substitute_tokens` supports BOTH `output_format="latex"` and `"html"` (LaTeX emits `\hyperlink`, HTML emits plain value). PRD §16 row 9 only mentioned LaTeX path. Raises `SubstitutionFailure(TRC003)` on unresolved label. §16 row 9 expanded. |
| OQ-NEW-82 | yes | 2026-05-06 (ralph-55) | Both `code_appendix.generate_code_appendix(runs)` and `notes_appendix.generate_notes_appendix(store, cited_labels)` return **empty string** when no inputs — caller MUST NOT include the section in the manuscript when empty. Loop must check return value before splicing. §16 rows 13-14 expanded. |
| OQ-NEW-83 | yes | 2026-05-06 (ralph-55) | `code_appendix` uses `_CodeRun` Protocol (structural typing) for the run input. Required attrs: `run_id: str`, `code: str`, `code_filename: str`, `producing_lines: tuple[int, ...]`. Works with `StubCodeRun` in tests OR `ExperimentRun` in production. Loop must implement either real or stub conforming to this Protocol. §16 row 13 expanded. |
| OQ-NEW-84 | partial | 2026-05-06 (ralph-55) | `notes_appendix.generate_notes_appendix` **silently skips labels not in store** (`if label not in store.products: continue`). Means a label cited in body could be missing from notes appendix without warning. Refactor opportunity: change to fail-loud per §6.10 hard-fail philosophy. v2.6.0 candidate; recorded so loop doesn't drift further. |
| OQ-NEW-85 | yes | 2026-05-06 (ralph-56) | ABORTING_PHRASES has **9 entries, not 4** as earlier PRD said. Verified verbatim from `validators.py:42-45`: `[insert`, `[unknown`, `[to be determined`, `[to be` (broader), `subject to revision`, `pending full search`, `<insert`, `<unknown`, `<missing` (3 angle-bracket variants for HTML-style placeholders). Case-INSENSITIVE matching. §6.11.T2 corrected. |
| OQ-NEW-86 | partial | 2026-05-06 (ralph-56) | **Discrepancy**: `validators.py` raises `UnexpectedModelBehavior` for aborting phrases, but `errors.py` defines `NumericValidatorAbort(error_code="TRC002")` for the same conceptual case. Loop should reconcile — either use TRC002 in validators or remove the unused class from errors. Recorded for v2.6.0; not blocking v2.5.0 since both behaviors are "fail-loud, no retry" semantically. |
| OQ-NEW-87 | yes | 2026-05-06 (ralph-56) | Numeric pattern requires preceding context character `[$,{<=\s\n\(\[]` (`must_follow` constraint at validators.py:60) — sophisticated false-positive prevention (e.g., `2024-05-01` dates won't match). `_strip_num_tokens` replaces `⟨num:label⟩` with `[NUM]` before bare-number scan to prevent labels-containing-numbers from triggering. Loop must NOT simplify the regex. |
| OQ-NEW-88 | yes | 2026-05-06 (ralph-56) | Label-not-in-store ModelRetry helpfully shows up to 10 available labels: `f"Available labels (showing up to 10): {list(store.products.keys())[:10]}"`. Helps the LLM self-correct on the next retry. Loop adding new validators should follow this "tell the model what's available" pattern. |
| OQ-NEW-89 | yes | 2026-05-06 (ralph-57) | `traceability/context_spec.py` only DEFINES the `ContextSpec` Pydantic class (25 lines, 2 fields). PRD §6.10.T2 said "move from global definitions in context_spec.py" — but NO global instances exist there. Actual work: define per-agent INSTANCES in each agent's home module (e.g., `DRAFT_WRITER_CONTEXT_SPEC` in `writing/agents.py`); class stays at `traceability/context_spec.py`. §6.10.T2 + §6.10.T3 + §16 row 10 corrected. |
| OQ-NEW-90 | yes | 2026-05-06 (ralph-57) | `Literal["all"]` sentinel in `allowed_numerical_labels` means "full store, no filtering" — distinct from `[]` which means "no labels allowed at all". Loop must use the right one for each agent (e.g., `independent_verifier` likely needs `"all"`; `intake` needs `[]`). §16 row 10 expanded. |
| OQ-NEW-91 | yes | 2026-05-06 (ralph-57) | `runtime/context.py::build_curated_context(state, spec)` raises `TypeError` if `spec` is NOT a `ContextSpec` instance (verified `context.py:104-105`). NO duck typing — loop must pass actual `ContextSpec` instances, not dict-of-fields. §6.10.T3 expanded with this constraint. |
| OQ-NEW-92 | yes | 2026-05-06 (ralph-58) | `citation_resolver.py` has **3 resolver functions, not 1**: `resolve_citations_to_cite_commands` (LaTeX natbib `\cite{}`), `resolve_citations_to_numbers` (`[1, 2]` numbered), `resolve_citations_to_pandoc` (pandoc `[@bibkey]`). Loop must pick the right function per render path (template-dependent). Plus heuristic `extract_cite_tokens` for downstream tooling. §6.7 current state expanded. |
| OQ-NEW-93 | yes | 2026-05-06 (ralph-58) | Pandoc multi-key citation uses **semicolon** separator: `[@a; @b]`, NOT comma `[@a,@b]`. PandocConvention. Loop wiring pandoc render path must follow. §6.7 current state expanded. |
| OQ-NEW-94 | yes | 2026-05-06 (ralph-58) | Adjacency merging in citation_resolver requires BOTH keys present in `ref_map` — mixed known/unknown leaves both alone. Unknown brackets (clinical trial IDs `[NCT12345]`, CVE `[CVE-...]`, equation labels `[IV]`) pass through UNCHANGED. Loop must NOT add a fallback that touches unknown brackets — would break manuscripts with non-citation bracket content. §6.7 current state expanded. |
| OQ-NEW-95 | yes | 2026-05-06 (ralph-59) | `paper_renderer.py` has **2 public renderers**: `render_markdown` (pandoc YAML frontmatter) + `render_latex` (direct LaTeX). Production uses pandoc path with `--natbib` + **`acl_natbib.bst`** (bibliography style file PRD §6.7 didn't mention). §6.7 current state expanded. |
| OQ-NEW-96 | yes | 2026-05-06 (ralph-59) | **`[FIGURE: N]` marker contract**: missing markers are LEFT IN PLACE (visible gap to author), NOT silent-skipped. This is an explicit anti-pattern — silent figure-resolution failures would let papers ship with broken markers. Loop must NOT add a fallback that hides missing figures. §6.7 current state expanded. |
| OQ-NEW-97 | yes | 2026-05-06 (ralph-59) | Renderer conventions: (a) abstract is in YAML frontmatter (`abstract: \|` folded literal), NOT a section — section heading `"abstract"` is skipped case-insensitively; (b) `ref_map` is 1-indexed (`enumerate(refs, 1)`), important when wiring numbered references; (c) multi-author format `"name, affiliation"` joined with `"; "` (semicolon) in YAML `author` field. §6.7 current state expanded. |
| OQ-NEW-98 | yes | 2026-05-06 (ralph-60) | **CRITICAL ANTI-PATTERN**: latex_compiler MUST NOT add `--biblatex` or `-V biblio-style`. acl.sty calls `\bibliographystyle{acl_natbib}` internally at `acl.sty:195`; a second `\bibstyle` crashes bibtex with `"Illegal, another \bibstyle command"`. Adding what looks like a missing flag would silently break every ACL build. §6.7 current state expanded with the exact comment + line reference. |
| OQ-NEW-99 | yes | 2026-05-06 (ralph-60) | `--natbib --bibliography=...` flags are CONDITIONAL — only added when `bib_source` is truthy. Without this guard, pandoc emits `\bibliography{references}` that tectonic fails on (no .bib file). Loop must preserve the conditional. §6.7 expanded. |
| OQ-NEW-100 | yes | 2026-05-06 (ralph-60) | Exact pandoc command documented: `pandoc paper.md -o paper.pdf --pdf-engine=tectonic -V documentclass=article -V classoption=11pt --number-sections --include-in-header=acl-header.tex --lua-filter=longtable-to-table-star.lua`. Per-build asset copy via `_copy_acl_assets(output_dir)` because pandoc resolves filter/header paths relative to cwd. §6.7 expanded. |
| OQ-NEW-101 | yes | 2026-05-06 (ralph-61) | Dashboard data model: 4 frozen dataclasses (NodeInfo, StageInfo, WatchdogAction, RunState) + 5 pure functions. `read_events` philosophy: "the dashboard is a derived view, not a system of record" — NEVER raises, returns empty list on missing file. §6.8 current state expanded. |
| OQ-NEW-102 | yes | 2026-05-06 (ralph-61) | **THIRD status concept discovered**: `StageInfo.status` (4 values: pending/running/completed/error) — distinct from PipelineStatus enum (6 values) AND RunState.pipeline_status (5 values). Three status types, none interchangeable. §18.6 "Two status concepts" subsection expanded to three. |
| OQ-NEW-103 | yes | 2026-05-06 (ralph-61) | `WatchdogAction.action` Literal verified verbatim: 5 values (`"killing"`, `"killed"`, `"resuming"`, `"resumed"`, `"aborted"`). Strips the `watchdog_` prefix from event_type when stored on the dataclass. Matches §18.2 5-watchdog-event-type set verified iters 27-28. |
| OQ-NEW-104 | yes | 2026-05-06 (ralph-62) | `dagster_runner.py` is a 2-step subprocess chain: `uv sync` (600s HARDCODED, not configurable) → `uv run dagster job execute -m pipeline.definitions` (configurable, default 1800s matching config.py). Loop tweaking timeouts must know `uv sync` is hardcoded. §6.2 expanded. |
| OQ-NEW-105 | yes | 2026-05-06 (ralph-62) | **Template-to-workspace copy invariant**: template at `templates/dagster-experiment/src/pipeline/definitions.py` becomes `src/pipeline/definitions.py` in workspace (the runner expects the latter path per Python `-m` resolution). Loop modifying §6.2.T1 template-copy step must preserve — otherwise Dagster import fails. §6.2 expanded. |
| OQ-NEW-106 | yes | 2026-05-06 (ralph-62) | `DagsterRunResult.succeeded = (returncode == 0 AND results_path.exists())` — BOTH required. Dagster can exit 0 but fail to write results.json. Loop must NOT short-circuit on returncode alone. §6.2 expanded. |
| OQ-NEW-107 | yes | 2026-05-06 (ralph-63) | **MAJOR PATH CORRECTION**: ralph-19/26/62 wrongly claimed template path was `templates/dagster-experiment/pipeline/definitions.py`. ACTUAL path is `templates/dagster-experiment/src/pipeline/definitions.py` — verified via `ls templates/dagster-experiment/` showing `src/` at top level. There is NO `pipeline/ → src/pipeline/` transformation; template_copier preserves structure. Earlier claim was wrong. Fixed all 7 PRD occurrences via replace_all. §6.2 + §15 + §6.7 corrected. |
| OQ-NEW-108 | yes | 2026-05-06 (ralph-63) | `template_copier.py` `_EXCLUDE_DIRS` (8 entries verbatim): `tests`, `.venv`, `__pycache__`, `.pytest_cache`, `.dagster`, `.dg`, `htmlcov`, `.ruff_cache`. `_EXCLUDE_FILES` (2 entries): `uv.lock`, `.coverage`. Loop adding new files to template must update these sets if not part of the workspace runtime. §6.2 expanded. |
| OQ-NEW-109 | yes | 2026-05-06 (ralph-63) | `_find_repo_root()` walks up from `__file__` looking for `templates/dagster-experiment/` directory — fails with `FileNotFoundError("Could not locate templates/dagster-experiment from package")` if not found. Loop must NOT delete this directory or rename the template name. The `_TEMPLATE_NAME = "dagster-experiment"` constant at line 11 — change here requires coordinated rename across all template-related code. |
| OQ-NEW-110 | yes | 2026-05-06 (ralph-64) | **MAJOR ARCHITECTURE CORRECTION**: NO `strategies/` directory exists in the Dagster template. Actual structure: `assets/_common/` (fixed infra) + `assets/experiment/` (auto-discovered per-run @asset modules generated by `config_writer` agent). Earlier PRD §6.2.T1-T4 + §15 §6.2 row referenced `strategies/` — wrong path. Stage 3-6 work (T1-T4) is REFRAMED: extend `config_writer` prompt + add canonical examples to `templates/dagster-experiment/examples/`, NOT add files under `strategies/`. Plus add `@asset_check` invariants in `assets/_common/`. §6.2.T1-T4 + §15 + current state corrected. |
| OQ-NEW-111 | yes | 2026-05-06 (ralph-64) | Workspace contract documented per `definitions.py` docstring: "read config.yaml, write to DuckDB tables, log to MLflow, write final artifacts to results.json + figures/*.png". Loop modifying experiment must preserve this contract. Resources are FIXED (ConfigResource + DuckDB + MLflow); only `pipeline/assets/experiment/*` modules vary per-run. §6.2 expanded. |
| OQ-NEW-112 | yes | 2026-05-06 (ralph-64) | Template's `src/pipeline/` package contents verified verbatim: `definitions.py` (2.2K), `config_models.py` (1.7K), `resources.py` (2.0K), `_publication_style.py` (3.0K), `__init__.py` (1020B), `assets/` subpackage (with `_common/` and `experiment/` sub-subpackages), `defs/` subpackage (currently empty `__init__.py` only — forward-looking placeholder). Loop must NOT add `strategies/` subdirectory; agent-generated content goes in `assets/experiment/`. |
| OQ-NEW-113 | yes | 2026-05-06 (ralph-65) | **MAJOR DESIGN-PHILOSOPHY CORRECTION**: `config_models.py` is ORCHESTRATION-ONLY (4 top-level fields: schema_version, dataset, mlflow, reproducibility). Algorithm-specific config (problem.type, AutoGluon presets, metric specs, modality columns, partitioning) is DELIBERATELY excluded — encoded in the agent-generated `@asset` modules instead. Earlier §6.2.T2/T3 said "add timeseries.partitioning" and "add multimodal.modality_columns" to `config_models.py` — both wrong, would violate the design philosophy. §6.2.T2/T3 reframed: extend `config_writer` agent prompt + add example `@asset` modules to `examples/`. §6.2 current state expanded. |
| OQ-NEW-114 | yes | 2026-05-06 (ralph-65) | DatasetConfig schema verified verbatim: 4 fields (`source: str`, `files: list[str]`, `entity_id_column: str`, `date_column: str \| None = None`). `source` accepts 3 schemes: `huggingface://org/repo` / `file://path` / `http(s)://url`. **`entity_id_column` MUST NEVER be used as a feature** — explicit constraint in Field description. `date_column` already exists for time-series — no schema change needed for Stage 4. Loop adding new dataset sources must update the `source` description. |
| OQ-NEW-115 | yes | 2026-05-06 (ralph-66) | `resources.py` (65 lines) verified: 3 classes (ConfigResource / DuckDBResource via factory / MLflowResource) + 1 helper `workspace_dir()` returning `Path.cwd()`. **Workspace cwd convention**: Dagster process launched with `cwd=workspace/` per dagster_runner — resources resolve paths against this. Loop must preserve. §6.2 expanded. |
| OQ-NEW-116 | yes | 2026-05-06 (ralph-66) | **`yaml.safe_load`** used in `ConfigResource.get()` (NOT `yaml.load` — security-critical). Loop must NOT change to plain `yaml.load` even if tools suggest it (would allow arbitrary code execution from a malicious config.yaml). |
| OQ-NEW-117 | yes | 2026-05-06 (ralph-66) | **DuckDB single-store invariant**: `workspace/experiment.duckdb` is "single store for all materializations" per `make_duckdb_resource()` docstring. Loop must NOT add multiple .duckdb files for different experiment phases — architectural constraint that simplifies cross-asset queries. |
| OQ-NEW-118 | yes | 2026-05-06 (ralph-66) | **MLflow nested-run pattern**: per `MLflowResource` docstring "Each asset opens nested runs via `mlflow.start_run(nested=True)`". Loop generating @asset code (config_writer prompt extension in §6.2.T1-T4) must include `nested=True`. Without it, MLflow run hierarchy collapses. Tracking URI file-backed at `workspace/mlruns/`. |
| OQ-NEW-119 | yes | 2026-05-06 (ralph-67) | **CRITICAL DAGSTER ANTI-PATTERN**: `from __future__ import annotations` MUST BE OMITTED in any module containing `@asset`/`@asset_check`. Reason (verified data_load.py:5-8): "Dagster's `@asset` decorator inspects parameter annotations at runtime and does identity comparisons. PEP 563 deferred annotations break that check." Loop generating per-experiment `@asset` modules MUST omit — even though the rest of the codebase uses future annotations universally. Added as §28 AP46. |
| OQ-NEW-120 | yes | 2026-05-06 (ralph-67) | CSV-loading invariant: `sample_size=-1` + `null_padding=true` REQUIRED. Defaults would silently corrupt datasets with widening type ranges (rossmann StateHoliday case verified). Loop generating new CSV-reading code must preserve. Added as §28 AP47. |
| OQ-NEW-121 | yes | 2026-05-06 (ralph-67) | `data_load.py` `_resolve()` supports 3 source schemes: `huggingface://org/repo` (via hf_hub_download), `file://path` (local), `http(s)://...` (DuckDB direct URL). Plus fallback "treat as local path" for tests/fixtures. 2 file extensions only: `.csv`, `.parquet`/`.pq` — others raise ValueError. Loop adding new format support must extend dispatch. §6.2 expanded. |
| OQ-NEW-122 | yes | 2026-05-06 (ralph-67) | Table-naming convention: `f"raw_{Path(filename).stem.replace('-', '_')}"` — dashes converted to underscores for SQL safety. Loop generating new table-creating code in agent-generated @asset modules must follow this convention to maintain query-ability against `raw_*` tables. §6.2 expanded. |
| OQ-NEW-123 | yes | 2026-05-06 (ralph-68) | **TWO timeout paths through L2 recovery** (verified `runtime/trace_logger.py:21` vs `recovery/bounded_run.py:41`). `bounded_agent_run` direct default = 900s (15 min, used by 3 evaluator call sites). `traced_agent_run` ALWAYS overrides via `_AGENT_RUN_TIMEOUT_S = 480.0` (8 min). Effective cap on the vast majority of pipeline agent runs is 480s. PRD §3.2 + §13.2 + §28 (AP10b/AP10c) updated. Loop must NEVER raise 480 ≥ 600 (watchdog max_idle_s) — that inversion was the run-0504-1802_ec44 regression. |
| OQ-NEW-124 | yes | 2026-05-06 (ralph-68) | **TraceLogger durable-disk-fallback layout** (`output/<run_id>/<phase>/traces/{NN}_{name}.md` + `traces/raw/{NN}_{name}.json`) is the operator-visible artifact when Logfire is down. Sequence number per-phase, NOT global. Tool returns truncated to 3000 chars in markdown only. Thinking truncated to 2000 chars. 8 part_kinds dispatched. JSON `text` parts auto-prettified to markdown via recursive `_json_to_md`. 3-fallback message serialization. §6.13 expanded with full layout + §28 AP52-AP55. |
| OQ-NEW-125 | yes | 2026-05-06 (ralph-68) | **EvaluationResult feedback format**: per `runtime/trace_logger.py:272-286`, feedback string is `" | "`-separated, each segment optionally prefixed with `[model_tag]` for per-model attribution. Renderer splits on ` | `, detects `[...]` prefix, extracts model_tag from first `]`. Loop modifying EvaluationResult format must preserve this convention or update the renderer in lockstep. |
| OQ-NEW-126 | yes | 2026-05-06 (ralph-68) | **Per-model scores table** (verified `trace_logger.py:287-302`): `EvaluationResult.per_model: list[PerModelEvaluation]` where each entry has `model_name: str` + `scores: dict[str, int]`. Renderer builds an N+2-column table (Dimension | model_1 | model_2 | model_3 | Median). Median is `eval_result.scores[dim]` — NOT recomputed from per_model. Loop must keep `eval_result.scores` semantically the median across `per_model` entries to avoid table drift. |
| OQ-NEW-127 | yes | 2026-05-06 (ralph-69) | **Hard-veto registry has exactly 2 entries at HEAD**: `no_placeholder_tokens` (7 patterns) + `no_bare_latex_commands` (≈82-entry math whitelist). Loop extending vetos MUST add to `runtime/hard_vetos.py` only — never inline in evaluator (AP59). §6.11 expanded with full pattern enumeration + AP56-AP60 codified. |
| OQ-NEW-128 | yes | 2026-05-06 (ralph-69) | **`[PENDING: ...]` SANCTIONED EXCEPTION** (`runtime/hard_vetos.py:24-25` docstring + `writing/specs/section_writer.yaml line 67-75`). Agents emit `[PENDING: ...]` deliberately for explicit deferrals; the `[INSERT...]` regex is HAND-TUNED to skip them. Loop must preserve the carve-out (AP56) and SectionWriter prompt must keep teaching agents this convention. |
| OQ-NEW-129 | yes | 2026-05-06 (ralph-69) | **`apply_hard_vetos` invariants**: (a) `verdict → "NEEDS_IMPROVEMENT"`, (b) `scores` UNCHANGED for postmortem (AP57), (c) `weakest_dimension = "hard_veto"` sentinel (NOT a rubric dimension — dashboard MUST special-case per AP58), (d) returns NEW frozen `EvaluationResult` (no mutation), (e) feedback prefixed `"HARD VETO: "` joined with `" | "`. Five invariants codified. |
| OQ-NEW-130 | yes | 2026-05-06 (ralph-69) | **LaTeX math whitelist categories** (verified `hard_vetos.py:57-76`): Greek lower 31 (incl. var-variants), Greek upper 11, math operators 7, decorations 14, relations 12, operators 7. Total ≈82 (PRD prose said "60+", actual count higher). Loop adding new symbols must keep the frozenset alphabetized within category for diff-readability. |
| OQ-NEW-131 | yes | 2026-05-06 (ralph-70) | **`score_trajectory.py` is STATELESS pure utility** (no class, no I/O, no module-level state). Persistence to `.pipeline_runs/<thread-id>_scores.json` is TARGET STATE in §6.11.T1, not yet implemented. Loop must NOT add hidden state to this module — keep persistence in a separate `score_persistence.py` module when shipping T1. |
| OQ-NEW-132 | yes | 2026-05-06 (ralph-70) | **CRITICAL TWO-SCALE INVARIANT**: `runtime/evaluator.py` uses 0-10 floats per rubric dimension; `runtime/score_trajectory.py` uses 0-100 ints from peer-review text. AP62 codifies the prohibition on implicit conversions. Conversion site (if added) must do `int(round(eval_score * 10))` and document at the boundary. |
| OQ-NEW-133 | yes | 2026-05-06 (ralph-70) | **8 DIMENSIONS** (`score_trajectory.DIMENSIONS`): argument_strength, evidence_quality, methodological_rigor, writing_clarity, citation_accuracy, structural_coherence, originality, overall. Loop must update `DIMENSIONS` + `_LABEL_TO_SNAKE` + every reviewer YAML rubric in lockstep when adding (AP61). |
| OQ-NEW-134 | yes | 2026-05-06 (ralph-70) | **Default thresholds**: `detect_regression(threshold=-3)` flags drop ≥4pts; `check_early_stop(threshold=3)` requires ALL deltas <3 to declare convergence. Both ints (matching 0-100 scale). Tests in `test_score_trajectory.py` are bound to these defaults — changing requires test update + §6.11 contract amendment. |
| OQ-NEW-135 | yes | 2026-05-06 (ralph-70) | **Parse heuristics first-write-wins**: when reviewer text contains the same dimension twice (summary table at top + deep-dive table later), the FIRST occurrence wins (`if dim not in scores`). Loop must preserve this ordering — reviewer agent prompts assume the summary table is authoritative. |
| OQ-NEW-136 | yes | 2026-05-06 (ralph-71) | **observability.py is 174 lines, NOT 150 as PRD prose said**. Bundles 6 responsibilities: configure_ssl, configure_observability, install_keepalive_provider_patch, _SHARED_KEEPALIVE_CLIENT singleton, shutdown_observability, init_dbos+launch_dbos two-step lifecycle (with _cancel_stale_workflows pre-init). Loop refactoring this file MUST keep the 6 boundaries — they are bundled deliberately around process-lifecycle ordering. |
| OQ-NEW-137 | yes | 2026-05-06 (ralph-71) | **Both AsyncAnthropic AND AsyncOpenAI patched** with keepalive http_client (verified `observability.py:82-100`). OpenAI patched defensively even though GPT-5.2 was removed in v2.4.0 — for any future OpenAI usage. Loop adding new providers (Gemini, Vertex AI) MUST follow the same pattern: `__keepalive_patched__` sentinel + `kwargs.setdefault("http_client", ...)`. |
| OQ-NEW-138 | yes | 2026-05-06 (ralph-71) | **DBOS db_path hard-coded at `.pipeline_runs/dbos.sqlite`**. `_cancel_stale_workflows` pre-init is MANDATORY — without it, `DBOS.launch()` blocks forever recovering crashed PENDING workflows. Two-step lifecycle: `init_dbos()` BEFORE agents registered, `launch_dbos()` AFTER. Loop must NOT collapse to single-step or DBOS misses agents. AP68/AP69 codified. |
| OQ-NEW-139 | yes | 2026-05-06 (ralph-71) | **`runtime/parsing.py` is dialogue-health, NOT structured-output parsing** (verified — module has only `check_dialogue_health`, name is misleading). 7 agreement markers, 3 conflict-avoidance regexes (strict AND match), 3-consecutive sycophancy threshold, 5-message default window. AP70/AP71 codify the CONSECUTIVE + AND invariants. ZERO mentions in PRD before this iter — was a complete documentation gap. |
| OQ-NEW-140 | yes | 2026-05-06 (ralph-71) | **`_SHARED_KEEPALIVE_CLIENT` is the SINGLE connection pool for 38+ agents**. Per-agent client construction = 38 pools = 38× FD usage = no socket reuse. AP67 codified. Loop must trace through `_get_shared_keepalive_client()` for any new HTTP-client construction site, not call `httpx.AsyncClient()` directly. |
| OQ-NEW-141 | yes | 2026-05-06 (ralph-72) | **`runtime/context.py` was undocumented in PRD before this iter** despite being the most-called runtime utility (research/graph.py 11×, pipeline/nodes.py, writing/review subgraphs). 4 functions: extract_field_text, build_context, build_curated_context, format_health_prefix. Full contract added to §6.13 expanded subsection. AP72-AP76 codified. |
| OQ-NEW-142 | yes | 2026-05-06 (ralph-72) | **`build_context` SINGLE-POINT-OF-RESPONSIBILITY for revision_context** — verified `runtime/context.py:77`: `state.revision_context = None` after consumption. Adding another consumer of revision_context would either duplicate REVISION INSTRUCTIONS or read stale data. AP72 codified. Loop must NOT add direct readers — go through `build_context(..., node_name=...)`. |
| OQ-NEW-143 | yes | 2026-05-06 (ralph-72) | **`extract_field_text` dispatch order is load-bearing** — falsy → BaseModel → dict (with `["raw"]` short-circuit) → list → str fallback. The `dict["raw"]` carve-out catches state dicts that wrap raw LLM text. AP73 codified. Loop reordering would mis-stringify or bloat prompts. |
| OQ-NEW-144 | yes | 2026-05-06 (ralph-72) | **`ensure_ascii=False` is mandatory** in `runtime/context.py:28` JSON dumps because pipeline outputs Unicode trace tokens `⟨num:label⟩` (U+27E8/U+27E9). ASCII escape would corrupt the lookup. AP74 codified. Loop must thread `ensure_ascii=False` through all pipeline JSON-stringification sites. |
| OQ-NEW-145 | yes | 2026-05-06 (ralph-72) | **`spec.allowed_numerical_labels == "all"` is a STRING SENTINEL** — Literal["all"], NOT an iterable. Iterating it yields `'a'`, `'l'`, `'l'`. Loop MUST check sentinel value FIRST then treat iterable case. AP76 codified. |
| OQ-NEW-146 | yes | 2026-05-06 (ralph-72) | **`format_health_prefix` returns `""` not `None`** when no warnings — callers can unconditionally `prompt = format_health_prefix(...) + base_prompt`. Loop changing return type to `None` would break every concatenation site silently (TypeError on first iter under load). |
| OQ-NEW-147 | yes | 2026-05-06 (ralph-73) | **persistence.py is 373 lines** (not 14K — that was bytes). TWO TABLES: `snapshots` (per-graph-node, append-only with status state machine) + `pipeline_state` (PipelineState JSON, UPSERT semantics, separate from snapshots). PRD prose previously implied single table. AP81 codifies the collapse prohibition. |
| OQ-NEW-148 | yes | 2026-05-06 (ralph-73) | **Snapshot status state machine has 5 states**: `created` → `pending` → `running` → `success` | `error`. `reset_crashed_snapshots` resets BOTH `running` AND `error` to `created` (verified SQL `status IN ('running', 'error')`). PRD prose said only `running`. AP79 codified. |
| OQ-NEW-149 | yes | 2026-05-06 (ralph-73) | **CRITICAL TypeAdapter graceful fallback** in `_reset_crashed_sync` (lines 352-370): when called BEFORE `graph.iter_from_persistence` sets types (the legitimate resume-time path), patches data_json directly via JSON manipulation. Removing crashes every resume. AP78 codified. |
| OQ-NEW-150 | yes | 2026-05-06 (ralph-73) | **WAL journal mode mandatory** for watchdog + pipeline concurrent access. AP80 codifies. Default DELETE mode would lock DB during writes and deadlock the watchdog read path. |
| OQ-NEW-151 | yes | 2026-05-06 (ralph-73) | **NO UNIQUE constraint on `snapshots(run_id, snapshot_id)`** — Python-level dedup in `snapshot_node_if_new` via `load_all()` then membership check. AP77 codified. Loop adding UNIQUE constraint must change INSERT → INSERT OR IGNORE in lockstep or break idempotent retries with IntegrityError. |
| OQ-NEW-152 | yes | 2026-05-06 (ralph-73) | **JSON list-of-one trick**: `dump_json([snapshot])` strip `[]` for storage, `_load_all_sync` joins back as `"[" + ",".join(...) + "]"`. `build_snapshot_list_type_adapter` is a LIST-only adapter — no per-item validate exposed by pydantic-graph. AP82 codified. |
| OQ-NEW-153 | yes | 2026-05-06 (ralph-73) | **Async/sync split via `_graph_utils.run_in_executor`**: 8 sync helpers (`_insert_snapshot`, `_load_all_sync`, `_update_status_sync`, `_rewrite_data_json`, `_save_pipeline_state_sync`, `_load_pipeline_state_sync`, `_can_resume_sync`, `_reset_crashed_sync`). All connection-per-call try/finally close pattern. Loop adding helpers MUST follow exact pattern or leak file descriptors. AP83 codified the long-lived-connection prohibition. |
| OQ-NEW-154 | yes | 2026-05-06 (ralph-73) | **`_rewrite_data_json` after every status update** is mandatory — data_json is the authoritative source on resume, NOT the status column. Loop modifying status update path that skips the rewrite causes resume to see stale status. |
| OQ-NEW-155 | yes | 2026-05-06 (ralph-74) | **CRITICAL §6.8.T4 PRD-prose drift FIXED**: PRD said "Throttle dashboard.txt writes via runtime/throttle.py" — but throttle.py is a PydanticAI Hooks capability for before_model_request, NOT a generic file-write throttler. Wrong API surface entirely. Task rewritten to add inline debounce in dashboard.py with `min_interval_s = 0.25` (4 Hz). AP84 codified the prohibition. |
| OQ-NEW-156 | yes | 2026-05-06 (ralph-74) | **`call_count` is GLOBAL across all 38+ agents** — module-level singleton at `throttle.py:76`. Per-agent singletons would multiply burst rate by 38× (each agent gets its own freebie call). AP89 codified. Loop wanting per-agent throttle must use `make_throttle_hooks()` factory to build independent closure-scoped counters (test pattern). |
| OQ-NEW-157 | yes | 2026-05-06 (ralph-74) | **`delay` fetched FRESH per call** from `DEFAULT_CONFIG.tool_call_delay_seconds` (NOT cached at module load). AP86 codified. Allows runtime config mutation (tests lowering delay to 0 between cases). |
| OQ-NEW-158 | yes | 2026-05-06 (ralph-74) | **Error hooks differ in exception type**: `run_error` catches `BaseException` (logs + re-raises KeyboardInterrupt/SystemExit/CancelledError too), `model_request_error` catches only `Exception` (lower-priority retryable). AP87/AP88 codified the type narrowing prohibition + the must-re-raise contract. |
| OQ-NEW-159 | yes | 2026-05-06 (ralph-74) | **`asyncio.sleep` not `time.sleep`** in throttle hook (line 46) — `time.sleep` blocks event loop, freezing watchdog + dashboard + recovery layers simultaneously. AP85 codified. |
| OQ-NEW-160 | yes | 2026-05-06 (ralph-74) | **`# type: ignore[return-type]` on error hooks is BY DESIGN** — observability hooks must raise (not return), but type stubs expect `ModelRequestContext` return. The ignore comments document the intentional protocol mismatch. Loop "fixing" by returning request_context silently breaks PydanticAI's retry/abort logic. |
| OQ-NEW-161 | yes | 2026-05-06 (ralph-75) | **cli.py has EXACTLY 7 commands** (`run`, `resume`, `dashboard`, `watchdog`, `supervised-run`, `unseal-run`, `supervised-resume`). Full inventory + behavior added as new §13.6 with per-command default-divergence gotchas. AP90-AP95 codified (6 new). |
| OQ-NEW-162 | yes | 2026-05-06 (ralph-75) | **CRITICAL CLAUDE.md vs cli.py drift**: CLAUDE.md lines 64-68 document `research`/`write`/`review` individual phase commands but they DO NOT EXIST in cli.py. Either implement (matches docs, allows phase-by-phase debugging) or strip from CLAUDE.md. AP95 codifies. v2.5.0 decision needed. |
| OQ-NEW-163 | yes | 2026-05-06 (ralph-75) | **CRITICAL CLI/API default mismatch**: `cli.py::watchdog_cmd --poll 15` vs `WatchdogConfig.poll_interval_s = 30`. Programmatic and CLI paths get DIFFERENT polling rates. AP94 codifies. Recommend harmonizing at 30 (matches WatchdogConfig) before v2.5.0 cut. |
| OQ-NEW-164 | yes | 2026-05-06 (ralph-75) | **`cli.py::resume` calls PRIVATE `_load_pipeline_state_sync`** (line 253) — bypasses asyncio for one call. AP93 codifies. v2.6.0 candidate: expose async `load_pipeline_state(thread_id)` and migrate. |
| OQ-NEW-165 | yes | 2026-05-06 (ralph-75) | **`unseal-run` is a SQLite-surgery tool** for AbortNode-sealed runs (~180 lines). 6-entry phase→subgraph mapping (ResearchPhaseNode→_research, ExperimentPhaseNode→_experiment, WritePhaseNode→_write, PreIntegrityNode→_pre_integrity_0, ReviewPhaseNode→_review, FinalIntegrityNode→_final_integrity_0). Updates BOTH `status` column AND embedded `data_json["status"]` field. AP91 codifies the dual-update invariant. Loop adding new SQLite-surgery commands must follow. |
| OQ-NEW-166 | yes | 2026-05-06 (ralph-75) | **`supervised-run` forwards ONLY 2 flags** (`--force-experiment`, `--copilot`) — NOT `--no-eval`, `--durable`, `--authors`, `--revision`. AP90 codifies. Loop adding flags to `run` MUST also add forwarding logic in `supervised_run_cmd:388-392`. |
| OQ-NEW-167 | yes | 2026-05-06 (ralph-75) | **`cleanup-state` command (§6.9.T5) is UNIMPLEMENTED** — referenced in §6.9.T5 task but no `@app.command(name="cleanup-state")` decorator exists in cli.py. Phase 2 wiring required before T5 can ship. Open OQ. |

---

*End of PRD.*
