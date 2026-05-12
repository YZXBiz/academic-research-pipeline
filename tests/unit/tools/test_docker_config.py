"""Tests for Docker execution config fields."""
from __future__ import annotations

from academic_pipeline.config import PipelineConfig


def test_docker_config_defaults():
    config = PipelineConfig()
    assert config.experiment_use_docker is True
    assert config.experiment_docker_image == "academic-pipeline-sandbox:latest"
    assert config.experiment_docker_memory == "4g"
    assert config.experiment_docker_cpus == "2"
