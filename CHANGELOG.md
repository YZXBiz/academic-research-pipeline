# Changelog

All notable changes to the Academic Research Pipeline are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- **`fastapi` + `uvicorn[standard]`** direct dependencies (PRD §6.12.T7).
  Zero `src/` imports and no dashboard v2 HTTP endpoint shipped (§6.8.T5
  deferred per blockers.md). Removing trims ~30 transitive packages.
- **`pydantic-ai[mcp]` extra** — no MCP usage in `src/` per CLAUDE.md.
- **`pydantic-ai[dbos]` extra** — DBOS confirmed disabled (asyncio.gather
  cancel-scope conflict). DBOS code paths in `observability.py` and
  `sdk/pipeline.py` remain `try/except ImportError`-gated, so removal does
  not break imports or runtime.

### Kept
- **`defusedxml>=0.7.1`** as explicit pin (PRD §6.12.T7 option (a)).
  Transitive consumer (`py-serializable` via `cyclonedx` via `pip-audit`)
  exists; explicit pin guards against implicit-removal regression if a
  future change drops `pip-audit`.

## [2.4.0] — 2026-05-02

Reviewer-effort upgrade and src-layout migration. **Breaking** for state files.

### Added
- **`src/` layout** — package now installs from `src/academic_pipeline/`, matching the standard Python project structure used by mature open-source projects (TensorFlow, JAX, Pydantic). Catches editable-install bugs that flat layouts hide.
- **`configs/*.yaml` runtime tunables** loaded via pydantic-settings' built-in `YamlConfigSettingsSource`. No custom loader. Precedence: init kwargs > env > .env > `dev.yaml` > `default.yaml` > Python defaults.
- **`examples/`** directory with four runnable scripts demonstrating the SDK surface (`Pipeline`, `PipelineConfig`, `PipelineResult`, `DEFAULT_CONFIG`).
- **Per-subgraph cohesion**: agent YAML specs now live next to the code that loads them — `src/academic_pipeline/{research,writing,review,integrity,experiment}/specs/`. Open one folder, see everything that subsystem touches.
- **`py.typed` marker** so downstream consumers get type information.
- **Public API surface** at `src/academic_pipeline/__init__.py` with explicit `__all__` for `Pipeline`, `PipelineConfig`, `PipelineResult`, `DEFAULT_CONFIG`.

### Changed
- **All 7 reviewer/verifier agents promoted to `anthropic_effort: max`** (one tier above `xhigh`) via the provider-specific `model_settings.anthropic_effort` field. Affects: `eic`, `domain_reviewer`, `editorial_synthesizer`, `field_analyst`, `methodology_reviewer`, `perspective_reviewer`, `figure_verifier`, `independent_verifier`. The unified `Thinking` capability (which caps at `xhigh`) was removed from these YAMLs.
- **`max_tokens` raised to 128000** (Opus 4.7 model max) on `independent_verifier` and `figure_verifier` to give thinking-token headroom under `max` effort. Thinking tokens bill as output and count toward `max_tokens`.
- **Hard cutover from `models/domain.py`** — 1605-line monolith split per-subgraph into `models/{research,writing,review,integrity,experiment}.py`. Back-compat shim deleted; 98 imports rewritten.
- **`tools/` split into capability sub-packages** — `code_execution.py` and friends broken into focused modules.
- **`state/` → `core/`** and **`utils/` → `runtime/`** package renames for clearer responsibility boundaries.

### Removed
- **GPT-5.2 dependency** removed from the entire pipeline. Both `cross_model_verifier` and `figure_verifier` now run on Claude Opus 4.7. The `evaluator_models` default shrinks from `["openai:gpt-5.2", "anthropic:claude-opus-4-7"]` to `["anthropic:claude-opus-4-7"]`.
- **`devils_advocate_reviewer`** purged — was registered in the agent dict but never wired into `REVIEWER_AGENTS` or `graph.py`. Pure dead code.
- **`FallbackModel` wrapper** around the verifier — both legs were Opus, making it pointless. Resilience comes from the hang-recovery system instead.

### Renamed (BREAKING)
- `cross_model_verifier` → `independent_verifier` (file, agent name, registry key)
- `CrossModelVerificationReport` → `IndependentVerificationReport`
- `cross_model_report` → `independent_verification_report` (state field)
- `cross_model_name` → `independent_verifier_model` (config field, in `config.py` AND `configs/default.yaml`)

### Migration
- **State files in `.pipeline_runs/` from before 2026-05-02 are incompatible** due to the field renames above. Delete `.pipeline_runs/<thread-id>_state.json` before resuming any pre-2.4.0 run.

## [2.3.0] — 2026-05-01

Hang-recovery release. Solves the 1h+ wedged-in-recv class of failures observed against the LLM proxy.

### Added
- **4-layer hang-recovery system** (`src/academic_pipeline/recovery/`):
  - **L1 (transport):** `make_keepalive_async_client` — httpx `AsyncClient` factory with TCP keepalive socket options (`TCP_KEEPALIVE`, `TCP_KEEPINTVL`, `TCP_KEEPCNT`) injected into the underlying transport. Catches dead sockets at OS level.
  - **L2 (call):** `bounded_agent_run` — `asyncio.wait_for` wrapper around every `agent.run()` call, default 15-minute cap. Raises `AgentTimeoutError` on stall. Wired into `trace_logger.traced_agent_run` and the 3 evaluator call sites.
  - **L3 (process):** `Heartbeat` context manager — daemon-thread emits to `heartbeat.txt` every 30 s. NOT an asyncio task (which would starve under CPU-bound work).
  - **L4 (supervisor):** `WatchdogConfig` + `run_watchdog` loop — polls `events.jsonl` mtime + `heartbeat.txt` mtime; if stale ≥ 75 s, sends `SIGTERM` to the pipeline's process group, waits 10 s, then `SIGKILL`. Optionally auto-resumes via `make resume`. 3-strikes escalation aborts after 3 failed recoveries.
- **`supervised_run` launcher** (Tier-3 single-file pattern from agent-orchestrator / supervice / OpenClaw). Spawns the pipeline + watchdog as sibling subprocesses, each in its own process group via `os.setsid`. Routes resume through the same supervised path.
- **`ProcessLock` context manager** — atomic PID + PGID files for cross-process kill targeting.
- **CLI subcommands:** `python -m academic_pipeline supervised-run` and `watchdog`.
- **Makefile targets:** `run-experiment` (default, supervised), `run-experiment-debug` (no watchdog), `watchdog` (standalone).
- **`events.jsonl` + Rich dashboard** — append-only event log (`pipeline_start`, `stage_change`, `node_complete`, `node_error`, `pipeline_complete`, `pipeline_error`, `heartbeat`) is the single source of truth for pipeline progress. Dashboard is a pure renderer over the log via `read_events`/`apply_event`/`derive_state`/`render` in `runtime/dashboard.py`.
- **Multi-seed replication, plan-alignment verification, VLM figure review** in the experiment subgraph.

### Changed
- **`Provider` constructors monkey-patched** at import time to inject the keepalive httpx client into both Anthropic and OpenAI SDK instances, via a re-entrancy-safe sentinel attribute (`__keepalive_patched__`).
- **Single shared keepalive `httpx.AsyncClient`** across all SDK instances (cached via `_get_shared_keepalive_client()`) — avoids per-agent connection-pool leakage.

### Fixed
- **Race conditions** in supervised-resume: stale `output/latest` symlinks rejected via `min_mtime`; watchdog's own events excluded from the strike counter; PGID file unlinked before resume to avoid stale-process-group races.
- **Dead-watchdog detection**: supervisor warns and aborts if the watchdog dies before the pipeline.

## [2.2.0] — 2026-04-29 (approximate)

Experiment subgraph upgrades.

### Added
- AutoGluon full API support (`TabularPredictor`, `TimeSeriesPredictor`, `MultiModalPredictor`).
- Experiment improvement loop with judge agent (max 2 iterations).
- Email alert when datasets cannot be located (SMTP from `.env`).
- Dataset discovery via Exa search with URL verification before code generation.
- `AgentMessageCache` persists ML engineer conversation across judge loops and crash recovery.

## [2.1.0] — 2026-04-26 (approximate)

Interactive experiment phase.

### Added
- Interactive ML agent runs experiments in a persistent Docker container.
- Multi-model evaluator panel on design and analysis nodes.
- Dataset URL verification + AST safety scan for generated code.
- Known-safe data sources for v1: sklearn, ucimlrepo, HuggingFace datasets.

## [2.0.0] — 2026-04-24 (approximate)

Major restructure: pydantic-graph state machines across 5 subgraphs.

### Added
- 44-node pipeline across `research → experiment → writing → review → integrity` subgraphs.
- 38 PydanticAI agents defined entirely via YAML specs (`Agent.from_file`).
- `PromptedOutput` wrapper on all structured-output agents (Thinking compatibility).
- `FileStatePersistence` + `_reset_crashed_snapshots()` for resume.
- Per-node evaluator-optimizer with quality threshold gating.

[Unreleased]: https://github.com/YZXBiz/academic-research-pipeline/compare/v2.4.0...HEAD
[2.4.0]: https://github.com/YZXBiz/academic-research-pipeline/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/YZXBiz/academic-research-pipeline/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/YZXBiz/academic-research-pipeline/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/YZXBiz/academic-research-pipeline/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/YZXBiz/academic-research-pipeline/releases/tag/v2.0.0
