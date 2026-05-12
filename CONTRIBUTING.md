# Contributing

Thanks for your interest in the Academic Research Pipeline. This document covers how to set up the project locally, the conventions we follow, and how to land a change.

## Setup

```bash
git clone <repo-url> academic-pipeline
cd academic-pipeline
uv sync                      # install deps + dev tools
cp .env.example .env         # fill in ANTHROPIC_API_KEY, EXA_API_KEY, etc.
uv run pytest tests/ -x -q   # confirm baseline (~992 tests passing)
```

This project uses [`uv`](https://docs.astral.sh/uv/) for everything — dependency management, running scripts, testing, lint. Prefix every command with `uv run` so you get the project's pinned environment.

## Quick reference

| Command | What it does |
|---|---|
| `uv run pytest tests/ -x -q` | Run small (unit) tests — the default |
| `uv run pytest -m medium` | Run Docker-required medium tests |
| `uv run ruff check src/ tests/` | Lint |
| `uv run pyright src/academic_pipeline/` | Type-check |
| `make check` | Full quality gate: lint + types + tests |
| `make run-experiment TOPIC="..."` | Hang-recovery-supervised pipeline run |
| `make watchdog THREAD_ID=run-XXXX` | Standalone watchdog against a running pipeline |
| `uv run python -m academic_pipeline dashboard --watch --latest` | Live dashboard |

## Conventions

### Code style

- `from __future__ import annotations` at the top of every module.
- Type-only imports inside `if TYPE_CHECKING:` blocks.
- Frozen Pydantic models: `model_config = ConfigDict(frozen=True)`.
- Nodes are `@dataclass` classes inheriting `BaseNode[StateT, DepsT, RunEndT]`.
- No bare `list` or `dict` annotations — always parameterized.
- `logging.getLogger(__name__)` per module — no `print` statements.

### Agent definitions

- Agents live in `src/academic_pipeline/<subgraph>/specs/*.yaml`. Loaded with `Agent.from_file()` from the matching `<subgraph>/agents.py`.
- All structured-output agents use `output_type=PromptedOutput(Model)`.
- All agents use `Thinking: effort: xhigh` (unified) by default. Reviewers and verifiers use `model_settings: anthropic_effort: max` instead.
- All agent invocations go through `run_with_evaluation()` (quality-gated) or `traced_agent_run()` (utility). Never bare `agent.run()`.

### Tests

We use Google's small/medium/large taxonomy via pytest markers.

- `tests/unit/` — small tests, fast, no Docker. Run by default.
- `tests/integration/` — medium tests, Docker-required. Run with `-m medium`.
- `tests/medium/` — same idea.
- `pyproject.toml` sets `addopts = "-m 'not medium and not large'"`, so bare `pytest` runs only small tests.
- `tests/conftest.py` sets `ALLOW_MODEL_REQUESTS = False` — tests that accidentally hit a real API will fail loudly.
- Mock agents with `agent.override(model=TestModel(custom_output_text=json_text))`.
- `PromptedOutput` agents need valid JSON via the `_JsonSchemaTestData` helper.

### Surgical changes

- Touch only what your change requires. Don't "improve" adjacent code.
- Match existing style. Remove only what your change made unused.
- No backward-compat shims — hard cutover, fix every reader in the same commit.
- No comments explaining what code used to be — git log is canonical.
- Don't add error handling for scenarios that can't happen. Trust framework guarantees. Validate at system boundaries only.

## Workflow

### Branch + commit

```bash
git checkout main && git pull
git checkout -b feat/short-description    # or fix/, refactor/, docs/, chore/, test/
# ... make changes ...
make check                                 # local quality gate
git commit -m "feat(scope): one-line summary"
```

Commit message format: `<type>(<scope>): <summary>`. Types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`. Scope is the package or area, e.g., `feat(recovery): ...`, `docs(architecture): ...`. Body explains _why_, not _what_ (the diff says what).

For larger changes, write a spec under `docs/superpowers/specs/` (gitignored — local-only), then a plan under `docs/superpowers/plans/`, then implement.

### Pull request

- Push your branch and open a PR against `main`.
- Include a one-paragraph summary, a "test plan" checklist, and link to any related spec or issue.
- CI runs `make check`. Don't merge if it's red.
- Squash-merge by default. Commit history on `main` should be linear and atomic.

### What gets reviewed

- Correctness (does it do what the summary claims).
- Test coverage (was a regression test added if this fixes a bug).
- Adherence to the conventions above.
- Spec compliance if there's a linked spec.

## Reporting bugs

Open a GitHub issue with:
- A minimal reproduction (a topic + the exact command, or a code snippet).
- The expected vs. actual behavior.
- Relevant log lines from `output/<run-id>/events.jsonl` or `make watchdog` output if it's a runtime hang.
- Your environment: `uv run python --version`, OS, whether you're using LLM proxy or direct Anthropic.

## License

By contributing, you agree that your contributions will be licensed under the project's LICENSE.
