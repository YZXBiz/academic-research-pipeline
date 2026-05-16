"""Canonical benchmark-comparison @asset chain.

Replaces free-form agent codegen. Reads the parameterized ExperimentSpec
from the workspace's config.yaml (via app_config.experiment_spec) and
runs a fixed chain:

    raw_data -> prepared_data -> predictions -> metrics -> results_json

Each step is template-shipped Python — no agent codegen — so the
failure modes that haunted run-0515 (dangling deps, wrong import paths,
missing pip deps, wrong sklearn API) cannot recur. The agent's entire
job is filling the typed ExperimentSpec.
"""

import json

import pandas as pd
from dagster import AssetExecutionContext, asset
from dagster_duckdb import DuckDBResource

from pipeline import workspace_dir
from pipeline.config_models import ExperimentConfig
from pipeline.resources import ConfigResource

from pipeline.assets.experiment._canonical_helpers import (
    calibrate,
    compute_metric,
    identify_target_column,
    select_feature_columns,
    stratified_split,
    train_base_model,
)


def _spec_or_raise(cfg: ExperimentConfig):
    """The canonical chain requires the typed spec — refuse to limp along without it."""
    if cfg.experiment_spec is None:
        raise ValueError(
            "config.yaml is missing the `experiment_spec` block. The canonical "
            "@asset chain requires a parameterized ExperimentSpec; without it "
            "there's nothing for it to do."
        )
    return cfg.experiment_spec


@asset(deps=["raw_data"])
def prepared_data(
    context: AssetExecutionContext,
    app_config: ConfigResource,
    duckdb: DuckDBResource,
) -> None:
    """Load → identify target → split → persist 6 DuckDB tables for downstream."""
    cfg = app_config.get()
    spec = _spec_or_raise(cfg)

    with duckdb.get_connection() as conn:
        first_file = cfg.dataset.files[0]
        stem = first_file.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("-", "_")
        table = f"raw_{stem}"
        df = conn.sql(f"SELECT * FROM {table}").df()

        target_col = identify_target_column(list(df.columns), cfg.dataset.target_column_patterns)
        feature_cols = select_feature_columns(df, target_col, cfg.dataset.entity_id_column)
        context.log.info(
            "prepared_data: rows=%d target=%s n_features=%d", len(df), target_col, len(feature_cols)
        )

        split = stratified_split(df, feature_cols, target_col, seed=spec.random_seed)

        # Persist the 6 frames; downstream assets re-read by name. DuckDB
        # accepts pandas DataFrames in registered tables via the `register`
        # API. CREATE OR REPLACE TABLE AS SELECT * FROM df is the canonical
        # way to materialize.
        for name, frame in {
            "canon_X_train": split.X_train,
            "canon_X_cal": split.X_cal,
            "canon_X_test": split.X_test,
            "canon_y_train": split.y_train.to_frame(name=target_col),
            "canon_y_cal": split.y_cal.to_frame(name=target_col),
            "canon_y_test": split.y_test.to_frame(name=target_col),
        }.items():
            conn.register("__df_tmp", frame)
            conn.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM __df_tmp")
            conn.unregister("__df_tmp")

        meta = pd.DataFrame({"target_col": [target_col], "n_features": [len(feature_cols)]})
        conn.register("__meta_tmp", meta)
        conn.execute("CREATE OR REPLACE TABLE canon_meta AS SELECT * FROM __meta_tmp")
        conn.unregister("__meta_tmp")


@asset(deps=["prepared_data"])
def predictions(
    context: AssetExecutionContext,
    app_config: ConfigResource,
    duckdb: DuckDBResource,
) -> None:
    """For each (algorithm, calibration) combo, train and write test predictions."""
    cfg = app_config.get()
    spec = _spec_or_raise(cfg)

    with duckdb.get_connection() as conn:
        meta = conn.sql("SELECT * FROM canon_meta").df()
        target_col = str(meta["target_col"].iloc[0])
        X_train = conn.sql("SELECT * FROM canon_X_train").df()
        X_cal = conn.sql("SELECT * FROM canon_X_cal").df()
        X_test = conn.sql("SELECT * FROM canon_X_test").df()
        y_train = conn.sql("SELECT * FROM canon_y_train").df()[target_col]
        y_cal = conn.sql("SELECT * FROM canon_y_cal").df()[target_col]
        y_test = conn.sql("SELECT * FROM canon_y_test").df()[target_col]

    from pipeline.assets.experiment._canonical_helpers import TrainTestSplit

    split = TrainTestSplit(X_train, X_cal, X_test, y_train, y_cal, y_test)

    rows = []
    for algo in spec.algorithms:
        base = train_base_model(algo, split, seed=spec.random_seed, time_limit_s=spec.time_limit_s)
        for cal_method in spec.calibration_methods:
            calibrated = calibrate(cal_method, base, split, seed=spec.random_seed)
            y_prob = calibrated.predict_proba(split.X_test)[:, 1]
            context.log.info(
                "trained algo=%s cal=%s n_test=%d", algo.value, cal_method.value, len(y_prob)
            )
            rows.extend(
                {
                    "algo": algo.value,
                    "calibration": cal_method.value,
                    "row_idx": i,
                    "y_true": int(split.y_test.iloc[i]),
                    "y_prob": float(y_prob[i]),
                }
                for i in range(len(y_prob))
            )

    pred_df = pd.DataFrame(rows)
    with duckdb.get_connection() as conn:
        conn.register("__pred_tmp", pred_df)
        conn.execute("CREATE OR REPLACE TABLE canon_predictions AS SELECT * FROM __pred_tmp")
        conn.unregister("__pred_tmp")


@asset(deps=["predictions"])
def metrics(
    context: AssetExecutionContext,
    app_config: ConfigResource,
    duckdb: DuckDBResource,
) -> None:
    """Compute spec.metrics per (algorithm, calibration) pair on test predictions."""
    cfg = app_config.get()
    spec = _spec_or_raise(cfg)

    with duckdb.get_connection() as conn:
        pred_df = conn.sql("SELECT * FROM canon_predictions").df()

    rows = []
    for (algo, cal_method), grp in pred_df.groupby(["algo", "calibration"]):
        y_true = grp["y_true"].to_numpy()
        y_prob = grp["y_prob"].to_numpy()
        for metric in spec.metrics:
            value = compute_metric(metric, y_true, y_prob)
            rows.append(
                {
                    "algo": algo,
                    "calibration": cal_method,
                    "metric": metric.value,
                    "value": value,
                }
            )
            context.log.info("metric algo=%s cal=%s %s=%.4f", algo, cal_method, metric.value, value)

    met_df = pd.DataFrame(rows)
    with duckdb.get_connection() as conn:
        conn.register("__met_tmp", met_df)
        conn.execute("CREATE OR REPLACE TABLE canon_metrics AS SELECT * FROM __met_tmp")
        conn.unregister("__met_tmp")


@asset(deps=["metrics"])
def results_json(
    context: AssetExecutionContext,
    app_config: ConfigResource,
    duckdb: DuckDBResource,
) -> str:
    """Write workspace/results.json from canon_metrics. AnalysisNode reads this."""
    cfg = app_config.get()
    spec = _spec_or_raise(cfg)

    with duckdb.get_connection() as conn:
        met_df = conn.sql("SELECT * FROM canon_metrics").df()

    # Reshape into {algo: {cal: {metric: value}}} for human readability + analyzer agent.
    nested: dict[str, dict[str, dict[str, float]]] = {}
    for _, row in met_df.iterrows():
        algo = str(row["algo"])
        cal = str(row["calibration"])
        metric = str(row["metric"])
        nested.setdefault(algo, {}).setdefault(cal, {})[metric] = float(row["value"])

    out: dict = {
        "schema_version": 1,
        "experiment_type": "benchmark_comparison_canonical",
        "spec": {
            "algorithms": [a.value for a in spec.algorithms],
            "calibration_methods": [c.value for c in spec.calibration_methods],
            "metrics": [m.value for m in spec.metrics],
            "random_seed": spec.random_seed,
        },
        "results_by_method": nested,
        "raw_metrics_table": met_df.to_dict(orient="records"),
    }

    target = workspace_dir() / "results.json"
    target.write_text(json.dumps(out, indent=2, default=str))
    context.log.info("wrote results.json: %d (algo, cal, metric) rows", len(met_df))
    return str(target)
