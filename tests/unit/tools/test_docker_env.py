"""Tests for DockerEnv (unit tests — no actual Docker)."""
from __future__ import annotations

from academic_pipeline.tools.execution.docker_env import DockerConfig, DockerEnv, _find_free_port


def test_docker_config_defaults():
    config = DockerConfig()
    assert config.container_name == "experiment-sandbox"
    assert config.workplace_name == "workspace"


def test_find_free_port():
    port = _find_free_port()
    assert 1024 < port < 65536


def test_docker_env_init():
    config = DockerConfig(container_name="test", communication_port=12345)
    env = DockerEnv(config)
    assert env.container_name == "test"
    assert env.communication_port == 12345
    assert env.docker_workplace == "/workspace"
