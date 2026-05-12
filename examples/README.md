# Examples

Each script demonstrates a specific feature of the academic-pipeline. Run from the repo root:

```bash
uv run python examples/basic_paper.py
uv run python examples/with_experiment.py
uv run python examples/with_authors.py
uv run python examples/supervised_run.py
uv run python examples/run_with_acl_template.py       --dry-run
uv run python examples/run_with_breadth_mode.py       --dry-run
uv run python examples/inspect_cascade_verdict.py     --dry-run
uv run python examples/replay_from_events_jsonl.py    --dry-run
```

| Script | Demonstrates |
|---|---|
| `basic_paper.py` | Minimal Pipeline run with mocked agents (offline) |
| `with_experiment.py` | Forces the experiment subgraph; mocked AutoGluon |
| `with_authors.py` | Passes `PaperConfig.authors` so the title page is filled |
| `supervised_run.py` | Programmatic supervised-run with watchdog + heartbeat |
| `run_with_acl_template.py` | `target_journal="ACL"` conference-style PaperConfig (PRD §6.7) |
| `run_with_breadth_mode.py` | Spec 7 exploration-breadth bundling (`exploration_breadth_enabled=True`) |
| `inspect_cascade_verdict.py` | Spec 6 cascaded review — surfaces `state.cascade_result` |
| `replay_from_events_jsonl.py` | Pure-renderer replay of an existing events.jsonl |

All examples use `pydantic_ai.models.test.TestModel` so no API key is required.
For real runs, see `make run` and `make run-experiment` in the project root.

The four `run_with_*`, `inspect_*`, and `replay_*` scripts also accept
`--dry-run` so CI can smoke-test them in <1 second per PRD §29 OQ8 (full
runs only in `make test-large`).

Note: `examples/_helpers.py` contains the shared TestModel-override
helper used by basic_paper, with_experiment, and with_authors. It is
not a runnable script.
