"""Dependency injection container for PydanticAI agents and graph nodes."""

from __future__ import annotations

import logging
from collections.abc import Callable  # runtime: used in dataclass field default
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from academic_pipeline.config import DEFAULT_CONFIG, PipelineConfig

if TYPE_CHECKING:
    from academic_pipeline.tools.execution.docker_env import DockerEnv
    from academic_pipeline.runtime.trace_logger import TraceLogger


logger = logging.getLogger(__name__)


def _default_hitl_handler(message: str, node_name: str) -> str:
    """Default HITL handler — auto-continue without prompting."""
    logger.info("HITL checkpoint [%s] — auto-continuing", node_name)
    return "continue"


@dataclass
class PipelineDeps:
    """Per-run dependencies flowing through GraphRunContext and RunContext."""

    config: PipelineConfig
    hitl_handler: Callable[[str, str], str] = field(default=_default_hitl_handler)
    consecutive_continues: int = 0
    trace_logger: TraceLogger | None = None
    docker_env: DockerEnv | None = None
    template_called: bool = False
    predictor_type: str = "tabular"
    persistence_dir: Path = field(default_factory=lambda: Path(".pipeline_runs"))

    @classmethod
    def create(
        cls,
        config: PipelineConfig | None = None,
    ) -> PipelineDeps:
        """Create deps from config.

        Args:
            config: Pipeline configuration. Falls back to DEFAULT_CONFIG.

        Returns:
            A fully-wired PipelineDeps instance.
        """
        cfg = config or DEFAULT_CONFIG
        return cls(config=cfg)
