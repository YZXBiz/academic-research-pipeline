# Contributing to dagster-experiment template

## Hard rules (anti-pattern guards)

1. **One responsibility per asset.** Asset bodies over 60 lines of non-conversion code MUST be split. (Anti-pattern A7 — reverting to monolith.)
2. **No DuckDB ↔ DataFrame conversion outside `pipeline/strategies/_dataframe_bridge.py`.** (Anti-pattern A3 — glue-code accumulation.)
3. **No new ML algorithm imports outside `pipeline/strategies/`.** Assets dispatch by config; strategies own the algorithm.
4. **AutoGluon never sees the test set during fit.** Hold-out happens before AutoGluon. (Anti-pattern A1 — SCI overfitting risk.)
5. **Default preset is `good_quality`. `best_quality` only when ExperimentPlan justifies it.** (Anti-pattern A1.)
6. **Every asset must materialize a DuckDB table OR write a deterministic file** (figures, results.json). No state-only assets.

## Dagster gotchas (learned the hard way)

- **Use `app_config: ConfigResource`** as the parameter name, NOT `config:`. The bare name `config` collides with Dagster's op-Config-schema interpretation and breaks resource resolution.
- **Do NOT add `from __future__ import annotations`** in modules with `@asset` / `@asset_check` decorators. Dagster's `_validate_context_type_hint` does an identity check on `params[0].annotation` and PEP-563 deferred annotations break it.
- **Use `con.sql(...).to_arrow_table()` not `.arrow()`** when reading DuckDB → Arrow. `.arrow()` returns a `RecordBatchReader`, not a `pa.Table`, in current DuckDB versions.
- **`materialize()` takes asset_checks INSIDE its `assets=` list**, not as a separate `asset_checks=` kwarg. The kwarg was removed in recent Dagster.
- **`dg check` is a command group**: use `dg check toml`, `dg check defs`, or `dg check yaml`.

## Testing

- **Fast tests** (`uv run pytest`) — config validation, dataframe bridge, strategy unit tests on synthetic data.
- **Medium tests** (`uv run pytest -m medium`) — full Dagster `materialize()` runs against fixture datasets.

## Spec

`docs/superpowers/specs/2026-05-04-experiment-phase-dagster-template-design.md` (in the parent academic-pipeline repo).
