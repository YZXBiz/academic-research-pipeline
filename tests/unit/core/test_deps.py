"""Tests for PipelineDeps dataclass."""

from __future__ import annotations

from academic_pipeline.core.deps import PipelineDeps


class TestPipelineDeps:
    def test_creates_with_defaults(self) -> None:
        deps = PipelineDeps.create()
        assert deps.config is not None
