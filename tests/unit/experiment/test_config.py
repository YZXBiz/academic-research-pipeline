"""Tests for experiment subgraph config and enums."""

from __future__ import annotations

from academic_pipeline.config import PipelineConfig
from academic_pipeline.core.enums import Stage


def test_experiment_stage_exists():
    assert Stage.EXPERIMENT == "experiment"
    assert Stage.EXPERIMENT in list(Stage)


def test_experiment_config_defaults():
    config = PipelineConfig()
    assert config.experiment_timeout_seconds == 1800
    assert config.experiment_max_retries == 3
    assert config.experiment_enabled is True
    assert "pandas" in config.experiment_allowed_packages
    assert "scikit-posthocs" in config.experiment_allowed_packages
    assert "shap" in config.experiment_allowed_packages
