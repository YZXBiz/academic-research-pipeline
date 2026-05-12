"""Unit tests for AutoGluon template tools."""
from __future__ import annotations

import pytest

from academic_pipeline.tools.execution.autogluon_templates import (
    get_autogluon_tabular_template,
    get_autogluon_timeseries_template,
    get_autogluon_multimodal_template,
    get_autogluon_presets_info,
)


@pytest.mark.asyncio
async def test_tabular_template_returns_script():
    script = await get_autogluon_tabular_template(
        task_type="classification",
        eval_metric="accuracy",
        target_column="target",
        dataset_load_code="import pandas as pd; df = pd.DataFrame()",
    )
    assert "TabularPredictor" in script
    assert "label=" in script
    assert "results.json" in script
    assert "figures" in script


@pytest.mark.asyncio
async def test_timeseries_template_returns_script():
    script = await get_autogluon_timeseries_template(
        eval_metric="MASE",
        target_column="target",
        prediction_length=48,
        dataset_load_code="import pandas as pd; df = pd.DataFrame()",
    )
    assert "TimeSeriesPredictor" in script
    assert "prediction_length" in script
    assert "48" in script
    assert "results.json" in script
    assert "figures" in script


@pytest.mark.asyncio
async def test_multimodal_template_returns_script():
    script = await get_autogluon_multimodal_template(
        problem_type="classification",
        eval_metric="accuracy",
        target_column="label",
        dataset_load_code="import pandas as pd; df = pd.DataFrame()",
    )
    assert "MultiModalPredictor" in script
    assert "problem_type" in script
    assert "results.json" in script
    assert "figures" in script


@pytest.mark.asyncio
async def test_presets_info_covers_all_predictors():
    info = await get_autogluon_presets_info()
    assert "TabularPredictor" in info
    assert "TimeSeriesPredictor" in info
    assert "MultiModalPredictor" in info
    assert "WQL" in info
    assert "problem_type" in info


def test_old_template_name_removed():
    import academic_pipeline.tools.execution.autogluon_templates as mod
    assert not hasattr(mod, "get_autogluon_experiment_template")
