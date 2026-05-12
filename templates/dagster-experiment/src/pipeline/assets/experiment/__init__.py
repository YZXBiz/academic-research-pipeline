"""Per-experiment generated assets.

Modules in this package are written by the ``config_writer`` agent
fresh per experiment. Anything goes — feature engineering, model fits,
evaluations, KPI scoring, figures — as long as each module exposes
Dagster @asset / @asset_check functions.

The package is auto-discovered by ``pipeline.definitions._discover_experiment_modules``
on workspace startup.
"""
