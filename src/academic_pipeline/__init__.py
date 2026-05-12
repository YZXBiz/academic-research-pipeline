"""Academic Research Pipeline — PydanticAI multi-agent system.

SDK usage::

    from academic_pipeline import Pipeline

    result = await Pipeline("Impact of AI on education").run()
"""

from __future__ import annotations

from academic_pipeline.config import DEFAULT_CONFIG, PipelineConfig
from academic_pipeline.sdk.pipeline import Pipeline
from academic_pipeline.sdk.result import PipelineResult


__all__ = [
    "DEFAULT_CONFIG",
    "Pipeline",
    "PipelineConfig",
    "PipelineResult",
]
