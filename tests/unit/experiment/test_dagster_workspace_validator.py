"""Tests for the agent-output Dagster workspace dep validator.

The config_writer agent has a recurring failure mode: it emits
@asset modules whose `deps=[...]` list references upstream asset
names that don't exist (cv_metrics, predictions, model_probabilities,
raw_train — the latter the DuckDB table not the asset). Dagster
then either fails at module load or treats them as phantom external
assets, produces no results.json, and the pipeline silently writes a
[PENDING]-laden paper. The validator parses every @asset module in
the workspace with AST, collects every defined asset name + the
template-shipped names, and reports every dangling reference. The
caller (ConfigWriterNode) uses this to retry the agent with the
errors as feedback before kicking Dagster.
"""

from __future__ import annotations

from pathlib import Path

from academic_pipeline.experiment.dagster_workspace_validator import (
    DepValidationError,
    validate_dagster_deps,
)


def _write_module(workspace: Path, name: str, content: str) -> None:
    p = workspace / "src" / "pipeline" / "assets" / "experiment" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_validates_clean_workspace_with_only_raw_data_dep(tmp_path: Path) -> None:
    """An asset that deps on the template-shipped `raw_data` passes."""
    _write_module(
        tmp_path,
        "data_prep.py",
        '''from dagster import asset
@asset(deps=["raw_data"])
def data_prep():
    return 1
''',
    )
    errors = validate_dagster_deps(tmp_path)
    assert errors == []


def test_validates_chained_assets_within_workspace(tmp_path: Path) -> None:
    """Downstream assets that ref same-workspace upstream pass."""
    _write_module(
        tmp_path,
        "data_prep.py",
        '''from dagster import asset
@asset(deps=["raw_data"])
def data_prep():
    return 1
''',
    )
    _write_module(
        tmp_path,
        "train_eval.py",
        '''from dagster import asset
@asset(deps=["data_prep"])
def train_eval():
    return 1
''',
    )
    errors = validate_dagster_deps(tmp_path)
    assert errors == []


def test_flags_single_dangling_dep(tmp_path: Path) -> None:
    """A dep referencing an undefined asset raises a structured error."""
    _write_module(
        tmp_path,
        "results_json.py",
        '''from dagster import asset
@asset(deps=["cv_metrics"])
def results_json():
    return 1
''',
    )
    errors = validate_dagster_deps(tmp_path)
    assert len(errors) == 1
    err = errors[0]
    assert err.dangling_dep == "cv_metrics"
    assert err.asset_name == "results_json"
    assert err.module == "results_json.py"


def test_flags_multiple_dangling_deps_across_modules(tmp_path: Path) -> None:
    """Every dangling dep is reported (no early bail-out)."""
    _write_module(
        tmp_path,
        "figures.py",
        '''from dagster import asset
@asset(deps=["cv_metrics", "predictions"])
def figures():
    return 1
''',
    )
    _write_module(
        tmp_path,
        "results_json.py",
        '''from dagster import asset
@asset(deps=["cv_metrics"])
def results_json():
    return 1
''',
    )
    errors = validate_dagster_deps(tmp_path)
    dangling = sorted((e.dangling_dep, e.asset_name) for e in errors)
    assert dangling == [
        ("cv_metrics", "figures"),
        ("cv_metrics", "results_json"),
        ("predictions", "figures"),
    ]


def test_flags_raw_train_specifically(tmp_path: Path) -> None:
    """The historic `raw_train` (DuckDB-table-not-asset) bug is caught."""
    _write_module(
        tmp_path,
        "data_prep.py",
        '''from dagster import asset
@asset(deps=["raw_train"])
def data_prep():
    return 1
''',
    )
    errors = validate_dagster_deps(tmp_path)
    assert len(errors) == 1
    assert errors[0].dangling_dep == "raw_train"


def test_skips_underscore_helper_modules(tmp_path: Path) -> None:
    """Modules whose name starts with _ are helpers and not auto-loaded."""
    _write_module(
        tmp_path,
        "_helpers.py",
        '''# helper module — has functions but no @asset, won't be loaded
def util():
    return 1
''',
    )
    _write_module(
        tmp_path,
        "data_prep.py",
        '''from dagster import asset
@asset(deps=["raw_data"])
def data_prep():
    return 1
''',
    )
    errors = validate_dagster_deps(tmp_path)
    assert errors == []


def test_empty_workspace_returns_empty_errors(tmp_path: Path) -> None:
    """No generated modules = nothing to validate, no errors."""
    # Just create the dir structure without modules
    (tmp_path / "src" / "pipeline" / "assets" / "experiment").mkdir(parents=True)
    errors = validate_dagster_deps(tmp_path)
    assert errors == []


def test_error_message_is_actionable_for_agent_retry(tmp_path: Path) -> None:
    """The error has a render() suitable for feeding back to the agent."""
    _write_module(
        tmp_path,
        "results_json.py",
        '''from dagster import asset
@asset(deps=["cv_metrics"])
def results_json():
    return 1
''',
    )
    errors = validate_dagster_deps(tmp_path)
    rendered = errors[0].render()
    assert "cv_metrics" in rendered
    assert "results_json" in rendered
    assert "results_json.py" in rendered
    # Should be one line for easy concatenation into agent feedback prompt
    assert "\n" not in rendered.strip()


def test_error_class_is_frozen() -> None:
    """DepValidationError is immutable so it can't be mutated downstream."""
    import dataclasses

    err = DepValidationError(
        module="data_prep.py",
        asset_name="data_prep",
        dangling_dep="raw_train",
    )
    assert dataclasses.is_dataclass(err)
    # Try to mutate — should raise on frozen dataclass
    try:
        err.dangling_dep = "raw_data"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("DepValidationError should be frozen")
