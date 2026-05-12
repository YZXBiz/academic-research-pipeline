# dagster-experiment template

Workspace template the academic-pipeline copies into `output/<run-id>/02-experiment/workspace/` per run.

## How a run works

1. `ConfigWriterNode` writes `workspace/config.yaml` (validated against `pipeline.config_models.ExperimentConfig`).
2. `DagsterRunNode` runs `uv run dagster job execute -m pipeline.definitions` with cwd = workspace.
3. Dagster materializes assets in dependency order, persisting tables to `workspace/experiment.duckdb`, MLflow runs to `workspace/mlruns/`, figures to `workspace/figures/`.
4. `pipeline/assets/_common/aggregate.py` writes `workspace/results.json` — the artifact `AnalysisNode` reads.

## Local development

```bash
uv sync
uv run dagster dev    # http://localhost:3000 (UI)
uv run pytest         # unit tests (fast)
uv run pytest -m medium   # e2e tests against fixtures
```

See `examples/config_clustering_pharmacy.yaml` for a known-good config (added in P1.13).

## Layout

```
src/pipeline/
├── definitions.py              Dagster Definitions
├── resources.py                ConfigResource + DuckDBResource (+ MLflow in P1.2)
├── config_models.py            Frozen Pydantic ExperimentConfig schema
├── strategies/
│   ├── _dataframe_bridge.py    ALL DuckDB↔Arrow↔numpy conversions go here
│   ├── clustering.py           KMeans/Ward/GMM wrappers (P1.3)
│   └── tabular_supervised.py   AutoGluon TabularPredictor wrapper (P1.4)
└── assets/
    ├── _common/                data_load, features, validate_features, aggregate, figures
    └── clustering/             cluster_assignments, internal_validity, stability_bootstrap, kpi_eval
```
