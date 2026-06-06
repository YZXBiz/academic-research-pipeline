# CLAUDE.md — Academic Research Pipeline (v2.3.0)

## What This Is

Autonomous academic paper pipeline. Give it a topic, get a journal-ready paper.
44 nodes across 5 subgraphs (research → experiment → writing → review → integrity).
38 PydanticAI agents defined via YAML specs. Runs fully unattended.

## Version

v2.3.0 — Dataset discovery (Exa search), AutoGluon full API (tabular + timeseries + multimodal), email alerts, experiment improvement loop, VLM figure review, multi-seed replication, plan-alignment verification.

## Model + API (2026-05-11 cutover)

All 52 agent YAMLs use `model: openai:deepseek-v4-pro` and route through DeepSeek's
**official** OpenAI-compatible API at `api.deepseek.com/v1`. There is no Anthropic provider
in this project anymore.

Required env (see `.env` / `.env.example`):
```
OPENAI_API_KEY=sk-...                       # DeepSeek key from platform.deepseek.com
OPENAI_BASE_URL=https://api.deepseek.com/v1
```

Thinking mode is **on by default** (DeepSeek's `thinking.type` defaults to `enabled`, default
`reasoning_effort: high`). To push specific agents to max reasoning, add to their YAML:
```yaml
model_settings:
  extra_body:
    thinking:
      type: enabled
      reasoning_effort: max
```

Context window: 1,048,576 tokens (1M) for both `deepseek-v4-pro` and `deepseek-v4-flash`. No
proxy clamping. Web search is NOT a built-in model feature — agents that need web access call
Exa tools (`web_search_exa`) instead.

The prior dpapi.cn relay proxy (and the `-reasoner-search` model alias it exposed) has been
retired — never reintroduce it; the official API is cheaper, has the full 1M window, and
supports DeepSeek's native `thinking` param.

## Behavioral Guidelines

Think before coding. State assumptions explicitly. If uncertain, ask.

- **Simplicity first.** Minimum code that solves the problem. No speculative features, no abstractions for single-use code, no "flexibility" that wasn't requested.
- **Surgical changes.** Touch only what you must. Don't "improve" adjacent code. Match existing style. Remove only what YOUR changes made unused.
- **Goal-driven execution.** Transform tasks into verifiable goals. Write a brief plan with checks. Loop until verified.
- **Surface tradeoffs.** If multiple interpretations exist, present them. If a simpler approach exists, say so. Push back when warranted.

## How to Operate the Pipeline

### Run a paper (fire and forget)
```bash
uv run python -m academic_pipeline run "your research topic" --thread-id my-run
```
Takes 1-2 hours. Output saved to `output/`.

### Guided re-run with revision
```bash
uv run python -m academic_pipeline run "same topic" \
  --thread-id my-run \
  --revision "Change methodology to quantitative survey. Add 2024-2025 sources."
```

### Hang-recovery supervisor (NEW — default for run-experiment)

```bash
# Standard run — wraps pipeline in a supervisor that auto-recovers from
# LLM proxy hangs (1h+ wedged-in-recv class). Single command.
make run-experiment TOPIC="your research topic"

# Same but with no watchdog (debugging mode — pipeline crashes propagate
# straight to your terminal without auto-resume)
make run-experiment-debug TOPIC="your research topic"

# Run the watchdog standalone against an already-running pipeline
make watchdog THREAD_ID=run-XXXX
```

The supervisor:
- Spawns the pipeline + watchdog as sibling subprocesses (each in its own
  process group via `setsid`).
- Watchdog polls `output/<run-id>/events.jsonl` mtime + `heartbeat.txt`
  mtime; if stale ≥75s, sends `SIGTERM` to the pipeline's process group,
  waits 10s, then `SIGKILL`. Optionally auto-resumes via `make resume`.
- 3-strikes escalation aborts if 3 consecutive recoveries fail to advance
  events.jsonl (prevents infinite restart loops).

Spec: `docs/superpowers/specs/2026-05-01-hang-recovery-design.md`

### Run individual phases
```bash
uv run python -m academic_pipeline research "topic" --thread-id X
uv run python -m academic_pipeline write "topic" --thread-id X
uv run python -m academic_pipeline review --thread-id X
```
State persists between phases via `.pipeline_runs/<thread_id>_state.json`.

### Monitor via Logfire
Project: `research-demo` at logfire-us.pydantic.dev/yzxbiz/research-demo

### View pipeline dashboard
```bash
# Snapshot of the most recent run
uv run python -m academic_pipeline dashboard --latest

# Snapshot of a specific run
uv run python -m academic_pipeline dashboard <run-id>

# Live mode — refreshes every second until Ctrl-C
uv run python -m academic_pipeline dashboard --watch --latest
```
The dashboard reads `output/<run-id>/events.jsonl` (append-only event log written by
the pipeline as it runs). The same renderer also writes `output/<run-id>/dashboard.txt`
on every node completion, so `cat output/latest/dashboard.txt` still works for a quick
look without invoking the CLI.

## Build & Test

Always pass `--frozen` to `uv` — fresh re-resolves currently fail on a `pydantic-ai-skills`
transitive (`mistralai>=1.9.2` doesn't exist). The lockfile resolves cleanly.

```bash
uv sync --frozen                                       # install from lockfile
uv run --frozen ruff check src/academic_pipeline/ tests/   # lint
uv run --frozen pyright src/academic_pipeline/             # type check
uv run --frozen pytest tests/ -x -q                        # tests (729, small only)
make test-integration                                       # Docker integration tests (medium)
make check                                                  # full quality gate (lint + types + tests)
```

## Architecture

### Pipeline Flow
```
IntakeNode → ResearchPhaseNode → ExperimentClassifierNode
  ├── (needs experiments) → ExperimentPhaseNode → WritePhaseNode
  │                           ├── (failure + retries left) → ExperimentFixNode → ExperimentPhaseNode
  │                           └── (failure + max retries) → AbortNode
  └── (no experiments) → WritePhaseNode
→ PreIntegrityNode → ReviewPhaseNode → FinalIntegrityNode → FinalizeNode → SummaryNode
```

### Experiment Subgraph v2 (post-2026-05-04 cutover — Dagster template)

```
ExperimentClassifier → ExperimentDesigner → ConfigWriter → DagsterRun → Analysis → End
```

- **ConfigWriterNode** (single LLM call): reads ExperimentPlan, writes `workspace/config.yaml` validated against `pipeline.config_models.ExperimentConfig` (frozen Pydantic). No code generation.
- **DagsterRunNode** (no LLM, pure subprocess): copies `templates/dagster-experiment/` into workspace, runs `uv run dagster job execute -m pipeline.definitions`. Reads `results.json` back into `ExperimentResults` for AnalysisNode.
- **Workspace template** at `templates/dagster-experiment/` (Dagster + DuckDB + AutoGluon + sklearn + MLflow). Each ML lifecycle step is a `@asset` with per-step re-materialization on failure.
- **Anti-pattern A1 (SCI overfitting):** `tabular_supervised.fit_and_evaluate()` holds out test set BEFORE AutoGluon sees data; default preset `good_quality` not `best_quality`; both val + test metrics logged to MLflow.
- **InteractiveMLNode + JudgeNode are deprecated.** Class definitions kept for snapshot-deserialization compat; `.run()` raises with redirect to fresh run. Pre-cutover runs cannot resume.
- **Spec:** `docs/superpowers/specs/2026-05-04-experiment-phase-dagster-template-design.md`
- **Plan:** `docs/superpowers/plans/2026-05-04-experiment-phase-dagster-template-plan.md` (Phases 0-2 covered)

### Key Patterns
- **PromptedOutput**: All structured-output agents use `PromptedOutput(Model)` — required for reliable JSON shaping with the OpenAI provider against DeepSeek
- **Exa direct tools**: Bibliography + experiment designer use `web_search_exa`/`web_fetch_exa` plain tool functions (no MCP)
- **Agent invocation**: Always `run_with_evaluation()` (quality-gated) or `traced_agent_run()` (utility). Never bare `agent.run()`.
- **Independent verification**: `independent_verifier` agent does a second-pass review of research claims/citations; `figure_verifier` does VLM figure review. NOTE: as of the 2026-05-11 cutover both run on the same DeepSeek model as the primary writer — "independent" here means a separate pass, not cross-model. Restore true cross-model checking by adding the agent to `MODEL_OVERRIDES` in `.env`, e.g. `MODEL_OVERRIDES={"independent_verifier":"anthropic:claude-opus-4-8"}`. Model selection is centralized in `runtime.model_registry` (`config.default_model` + `config.model_overrides`); specs carry no model literal.
- **State persistence**: `PipelineState` serialized via `pydantic.TypeAdapter` to `.pipeline_runs/`
- **Crash recovery**: `FileStatePersistence` + `_reset_crashed_snapshots()` for resume
- **State-file compat note:** State files in `.pipeline_runs/` from before 2026-05-02 are incompatible (`cross_model_report` → `independent_verification_report`, `cross_model_name` → `independent_verifier_model`). Delete `.pipeline_runs/<thread-id>_state.json` before resuming pre-2026-05-02 runs.
- **Agent message cache**: `AgentMessageCache` persists ML engineer conversation via PydanticAI's `ModelMessagesTypeAdapter` for judge loop resume and crash recovery
- **Events log**: `output/<run-id>/events.jsonl` is the single source of truth for pipeline progress (`pipeline_start`, `stage_change`, `node_complete`, `node_error`, `pipeline_complete`, `pipeline_error`). The dashboard is a pure renderer over this log via `read_events`/`apply_event`/`derive_state`/`render` in `src/academic_pipeline/utils/dashboard.py`. No static node-to-stage map.

### Agents
- Defined via YAML specs co-located with each subgraph: `<sub>/specs/*.yaml`
- Loaded with `Agent.from_file()` in `<sub>/agents.py` registry files
- All specs start with `model: openai:deepseek-v4-pro` (post-2026-05-11). No `anthropic_effort` / `Thinking: effort:` fields — DeepSeek thinking mode is enabled by default; opt agents into `reasoning_effort: max` via `extra_body.thinking` only when explicitly needed
- All structured agents wrapped with `PromptedOutput()`

### Tools
Capability-grouped sub-packages under `src/academic_pipeline/tools/`:

- `tools/bibliography/` — citation + source verification
  - `bibtex.py` — BibTeX entry/file generation
  - `citations.py` — Citation formatting (APA7, Chicago, MLA, IEEE, Vancouver)
  - `doi.py` — DOI validation via CrossRef + retraction checks
  - `exa.py` — Exa web search + content fetch (direct API, no MCP)
  - `semantic_scholar.py` — Semantic Scholar API for paper metadata
- `tools/execution/` — sandboxed code execution + experiment tooling
  - `ast_safety.py` — AST-based script validation (`validate_script`, `ValidationResult`)
  - `subprocess_runner.py` — Docker/subprocess execution + artifact collection (`ExecutionResult`, `execute_script`)
  - `sanity.py` — `sanity_check_results`, `verify_plan_alignment`, `verify_dataset_urls`, `send_dataset_alert`
  - `containers.py` — PydanticAI tools that drive the persistent experiment Docker container
  - `docker_env.py` — `DockerConfig`/`DockerEnv` lifecycle for the experiment sandbox
  - `autogluon_templates.py` — Tabular/timeseries/multimodal AutoGluon script templates
- `tools/rendering/` — figure execution + LaTeX/PDF compilation
  - `figure_executor.py` — Run paper figure scripts in a sandbox
  - `latex_compiler.py` — Pandoc + tectonic PDF compilation
- `tools/agent_cache.py` — PydanticAI message history persistence for agent conversation resume
- `tools/integrity_tools.py` — Claims extraction + plagiarism heuristics

### Subagent Model Policy
- Always dispatch subagents with `model="opus"` or omit the model parameter to inherit the parent model.
- Never use `"sonnet"` or `"haiku"` for subagents.

### Code Standards
- `from __future__ import annotations` in every module
- Type-only imports in `if TYPE_CHECKING:` blocks
- Frozen Pydantic models: `model_config = ConfigDict(frozen=True)`
- Nodes are `@dataclass` classes inheriting `BaseNode[StateT, DepsT, RunEndT]`
- No bare `list` or `dict` — always typed
- `logging.getLogger(__name__)` per module, no print statements

### Testing
- Google test pyramid: `small` (unit, default), `medium` (Docker), `large` (real APIs)
- `addopts = "-m 'not medium and not large'"` in pyproject.toml — bare `pytest` runs small only
- `ALLOW_MODEL_REQUESTS = False` in conftest.py — catches tests accidentally hitting real APIs
- Mock agents with `agent.override(model=TestModel(custom_output_text=json_text))`
- PromptedOutput agents need valid JSON text via `_JsonSchemaTestData`
- Shared fixtures in `tests/conftest.py` (`make_test_model`, `make_test_deps`, `json_for_model`)
- `truststore.inject_into_ssl()` in conftest for Zscaler SSL
- Tests organized: `tests/unit/`, `tests/integration/`, `tests/medium/`

## Design System
Always read DESIGN.md before making any visual or UI decisions.
Do not deviate without explicit user approval.

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
