"""Tests for dataset discovery config fields."""
from __future__ import annotations

from academic_pipeline.config import PipelineConfig


def test_dataset_discovery_config_defaults():
    config = PipelineConfig()
    assert config.experiment_dataset_path == ""
    assert config.experiment_alert_email == ""
    assert config.experiment_alert_sender == ""
    assert config.experiment_smtp_server == ""
    assert config.experiment_smtp_port == 25
    assert "autogluon" in config.experiment_allowed_packages
