# tests/test_harness.py
"""Tests for experiment harness enforcement layers."""
from __future__ import annotations

import pytest

from academic_pipeline.experiment.harness import (
    ALLOWED_SKLEARN,
    FORBIDDEN_IMPORTS,
)


def test_forbidden_imports_contains_lightgbm():
    assert "import lightgbm" in FORBIDDEN_IMPORTS
    assert "from xgboost" in FORBIDDEN_IMPORTS
    assert "from sklearn.ensemble" in FORBIDDEN_IMPORTS


def test_allowed_sklearn_permits_dummy():
    assert "from sklearn.dummy" in ALLOWED_SKLEARN
    assert "from sklearn.metrics" in ALLOWED_SKLEARN
    assert "from sklearn.model_selection" in ALLOWED_SKLEARN


def test_forbidden_does_not_overlap_allowed():
    for allowed in ALLOWED_SKLEARN:
        assert allowed not in FORBIDDEN_IMPORTS


def test_harness_hooks_has_three_hooks():
    from academic_pipeline.experiment.harness import harness_hooks
    registry = harness_hooks._registry
    assert "before_tool_execute" in registry
    assert "after_tool_execute" in registry
    assert len(registry["after_tool_execute"]) >= 2


def test_template_gate_is_prepare_tools():
    from pydantic_ai.capabilities import PrepareTools
    from academic_pipeline.experiment.harness import template_gate
    assert isinstance(template_gate, PrepareTools)


def test_forbidden_imports_includes_autogluon_internals():
    assert "from statsforecast" in FORBIDDEN_IMPORTS
    assert "import gluonts" in FORBIDDEN_IMPORTS
    assert "from chronos" in FORBIDDEN_IMPORTS
    assert "import transformers" in FORBIDDEN_IMPORTS
    assert "from timm" in FORBIDDEN_IMPORTS


def test_allowed_autogluon_permits_all_predictors():
    from academic_pipeline.experiment.harness import ALLOWED_AUTOGLUON
    assert "from autogluon.tabular" in ALLOWED_AUTOGLUON
    assert "from autogluon.timeseries" in ALLOWED_AUTOGLUON
    assert "from autogluon.multimodal" in ALLOWED_AUTOGLUON
    assert "from autogluon.core" in ALLOWED_AUTOGLUON
    assert "import autogluon" in ALLOWED_AUTOGLUON


def test_template_map_has_all_predictor_types():
    from academic_pipeline.experiment.harness import TEMPLATE_MAP
    assert set(TEMPLATE_MAP.keys()) == {"tabular", "timeseries", "multimodal"}
    assert TEMPLATE_MAP["tabular"] == "get_autogluon_tabular_template"
    assert TEMPLATE_MAP["timeseries"] == "get_autogluon_timeseries_template"
    assert TEMPLATE_MAP["multimodal"] == "get_autogluon_multimodal_template"


def test_validate_experiment_plan_exists():
    from academic_pipeline.experiment.harness import validate_experiment_plan
    import asyncio
    assert asyncio.iscoroutinefunction(validate_experiment_plan)
