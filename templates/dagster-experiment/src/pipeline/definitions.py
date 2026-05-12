"""Dagster Definitions for the experiment workspace.

Loads two asset sources:
  1. ``pipeline.assets._common.data_load`` — fixed infra: HF download +
     DuckDB ingest of raw_<file> tables. Same for every experiment.
  2. ``pipeline.assets.experiment.*`` — generated per-experiment by the
     ``config_writer`` agent. ALL ML logic (feature engineering, model
     fits, evaluation, KPIs, figures) lives here as @asset / @asset_check
     functions. The agent is free to add as many modules as it wants —
     all of them are auto-discovered.

Resources are fixed (ConfigResource, DuckDB, MLflow); the workspace
contract is: read config.yaml, write to DuckDB tables, log to MLflow,
write final artifacts to results.json + figures/*.png.
"""

import importlib
import pkgutil
from types import ModuleType

from dagster import (
    Definitions,
    definitions,
    load_asset_checks_from_modules,
    load_assets_from_modules,
)

from pipeline.assets._common import data_load
from pipeline.resources import ConfigResource, MLflowResource, make_duckdb_resource


def _discover_experiment_modules() -> list[ModuleType]:
    """Import every module under pipeline.assets.experiment.

    Returns an empty list if the package doesn't exist (the agent hasn't
    generated any assets yet — useful for the empty smoke test).
    """
    try:
        pkg = importlib.import_module("pipeline.assets.experiment")
    except ModuleNotFoundError:
        return []
    modules: list[ModuleType] = []
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_"):
            continue
        modules.append(importlib.import_module(f"pipeline.assets.experiment.{info.name}"))
    return modules


@definitions
def defs() -> Definitions:
    experiment_modules = _discover_experiment_modules()
    _assets = load_assets_from_modules([data_load, *experiment_modules])
    _checks = load_asset_checks_from_modules([data_load, *experiment_modules])

    return Definitions(
        assets=_assets,
        asset_checks=_checks,
        resources={
            "app_config": ConfigResource(),
            "duckdb": make_duckdb_resource(),
            "mlflow": MLflowResource(),
        },
    )
