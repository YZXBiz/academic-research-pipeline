# SDK Surface

The public Python API for embedding the academic-pipeline in other tools.
Everything in this document is re-exported from `academic_pipeline/__init__.py`
and is the only surface guaranteed to be stable across patch releases.

```python
from academic_pipeline import (
    DEFAULT_CONFIG,    # PipelineConfig instance with library defaults
    Pipeline,          # entry point — construct, run, observe
    PipelineConfig,    # type-safe config (pydantic-settings)
    PipelineResult,    # final wrapped state after run
)
```

PRD anchor: §6.12 (Config + SDK Surface).

## `Pipeline`

The main entry point. Wraps the PydanticAI graph, persistence, lock files,
heartbeat, and event logging into one async-runnable class.

```python
import asyncio
from pathlib import Path
from academic_pipeline import Pipeline

async def main():
    pipeline = Pipeline(
        topic="Impact of LLMs on academic peer review",
        thread_id="my-run",
        interactive=False,
        persistence_dir=Path(".pipeline_runs"),
    )
    result = await pipeline.run(output_dir="output")
    print(result.paper_draft.title if result.paper_draft else "(no draft)")

asyncio.run(main())
```

Constructor signature (verified PRD §6.12):

| Param                   | Type                  | Default       | Notes                                                                             |
| ----------------------- | --------------------- | ------------- | --------------------------------------------------------------------------------- |
| `topic`                 | `str`                 | (required)    | Positional. The research topic.                                                    |
| `thread_id`             | `str \| None`         | autogen       | Format `run-MMDD-HHMM_xxxx` if omitted.                                            |
| `interactive`           | `bool`                | `True`        | False = HITL prompts auto-continue.                                                |
| `revision_instructions` | `str`                 | `""`          | Forces a revision pass when non-empty.                                             |
| `persistence_dir`       | `Path \| None`        | `.pipeline_runs` | Where SQLite + per-thread state files live.                                       |
| `use_dbos`              | `bool`                | `False`       | DBOS durable execution opt-in (currently disabled — see `project_dbos_compat`).   |
| `paper_config`          | `PaperConfig \| None` | `None`        | Pre-populated PaperConfig; bypasses the intake agent for that field.              |

### `Pipeline.observe(callback) -> Cancellable`

Subscribe to event emissions programmatically — cleaner than tailing
`events.jsonl`. Returns a zero-arg cancel function that unsubscribes.

```python
def on_event(event: dict) -> None:
    print(event["type"], event.get("stage"))

cancel = pipeline.observe(on_event)
await pipeline.run(output_dir="output")
cancel()
```

Observer exceptions are logged and swallowed — a bad callback cannot crash the
pipeline or starve sibling observers. PRD §6.12.T2.

### `Pipeline.run_stream(output_dir)` — async generator

Yields `PipelineEvent` values as nodes execute. Use this when you want
progress updates without waiting for the full run:

```python
async for event in pipeline.run_stream(output_dir="output"):
    print(event.type, event.data)
```

## `PipelineConfig`

Type-safe configuration. Reads from env vars, `.env`, then
`configs/{default,dev}.yaml` (in that precedence order).

```python
from academic_pipeline import PipelineConfig

cfg = PipelineConfig(
    model_name="claude-opus-4-7",
    node_quality_threshold=7.5,
    node_quality_thresholds={"draft_writer": 7.0, "synthesis": 8.0},  # §6.12.T5
    cascaded_review_enabled=True,
)
threshold = cfg.get_node_threshold("draft_writer")  # 7.0 (per-node override)
```

Read the [config.py](../../src/academic_pipeline/config.py) module for the full
field list (130+ settings). Helper methods:

- `get_temperature(agent_type)` → `float` per agent type
- `get_node_threshold(node_name)` → `float` with fallback to global default

## `PipelineResult`

The wrapped final state, returned from `Pipeline.run()`. A thin wrapper around
`PipelineState` exposing the result-relevant fields.

```python
result = await pipeline.run(output_dir="output")
print(result.paper_draft)         # PaperDraft | None
print(result.bibliography)        # list[Citation]
print(result.cascade_result)      # CascadeResult | None (if Spec 6 enabled)
result.save("output/my-run/")
```

## `DEFAULT_CONFIG`

A `PipelineConfig` instance constructed at import time with library defaults.
Use it when you want to inspect "what would happen with no overrides" without
constructing a fresh config (which re-runs YAML parsing + env var loading).

```python
from academic_pipeline import DEFAULT_CONFIG

print(DEFAULT_CONFIG.model_name)
print(DEFAULT_CONFIG.evaluator_models)
```

## Examples

The [`examples/`](../../examples/) directory ships runnable scripts that
double as smoke tests. Every script accepts `--dry-run` for CI use (per
PRD §29 OQ8 — full runs only in `make test-large`):

| Script                           | Demonstrates                                                                  |
| -------------------------------- | ----------------------------------------------------------------------------- |
| `basic_paper.py`                 | Minimal Pipeline run with mocked agents                                        |
| `with_experiment.py`             | Forces the experiment subgraph                                                 |
| `with_authors.py`                | Pre-populates `PaperConfig.authors`                                            |
| `supervised_run.py`              | Programmatic supervised run with watchdog + heartbeat                          |
| `run_with_acl_template.py`       | `target_journal="ACL"` conference-style PaperConfig                            |
| `run_with_breadth_mode.py`       | Spec 7 exploration-breadth bundling (`exploration_breadth_enabled=True`)       |
| `inspect_cascade_verdict.py`     | Spec 6 cascaded review — surfaces `state.cascade_result`                       |
| `replay_from_events_jsonl.py`    | Pure-renderer replay of an existing events.jsonl into the dashboard           |
