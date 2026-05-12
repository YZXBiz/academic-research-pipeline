"""Tests for Pipeline.observe(callback) — PRD §6.12.T2."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


def _drain(pipeline, out_dir: Path) -> None:
    """Run pipeline.run_stream(out_dir) until graph_build raises and swallow."""
    from unittest.mock import patch

    async def _run() -> None:
        async for _ in pipeline.run_stream(output_dir=str(out_dir)):
            pass

    with patch("academic_pipeline.pipeline.graph.build_pipeline_graph") as mock_build:
        mock_build.side_effect = RuntimeError("synthetic exit")
        with contextlib.suppress(RuntimeError):
            asyncio.run(_run())


def test_observe_receives_pipeline_start_event(tmp_path: Path) -> None:
    """Registered observer is invoked with the pipeline_start event."""
    from academic_pipeline.sdk.pipeline import Pipeline

    pipeline = Pipeline("topic", thread_id="t-obs1", interactive=False, persistence_dir=tmp_path)
    received: list[dict] = []

    cancel = pipeline.observe(received.append)
    assert callable(cancel)

    _drain(pipeline, tmp_path / "out")

    types = [e["type"] for e in received]
    assert "pipeline_start" in types
    start = next(e for e in received if e["type"] == "pipeline_start")
    assert start["run_id"] == "t-obs1"
    assert start["topic"] == "topic"


def test_observe_cancellable_unsubscribes(tmp_path: Path) -> None:
    """Calling the returned cancel function removes the observer from future emissions."""
    from academic_pipeline.sdk.pipeline import Pipeline

    pipeline = Pipeline("topic", thread_id="t-obs2", interactive=False, persistence_dir=tmp_path)
    received: list[dict] = []
    cancel = pipeline.observe(received.append)
    cancel()  # unsubscribe before any run

    _drain(pipeline, tmp_path / "out")

    assert received == []  # observer never fired


def test_observe_isolates_callback_exceptions(tmp_path: Path) -> None:
    """A raising observer must not crash the pipeline or block other observers."""
    from academic_pipeline.sdk.pipeline import Pipeline

    pipeline = Pipeline("topic", thread_id="t-obs3", interactive=False, persistence_dir=tmp_path)

    def bad(_event: dict) -> None:
        raise RuntimeError("observer boom")

    received: list[dict] = []
    pipeline.observe(bad)
    pipeline.observe(received.append)

    # Should NOT raise — observer exceptions are isolated.
    _drain(pipeline, tmp_path / "out")

    # The good observer still got events.
    assert any(e["type"] == "pipeline_start" for e in received)


def test_observe_multiple_callbacks_all_fire(tmp_path: Path) -> None:
    """All registered observers are notified for every emission."""
    from academic_pipeline.sdk.pipeline import Pipeline

    pipeline = Pipeline("topic", thread_id="t-obs4", interactive=False, persistence_dir=tmp_path)
    a: list[dict] = []
    b: list[dict] = []
    pipeline.observe(a.append)
    pipeline.observe(b.append)

    _drain(pipeline, tmp_path / "out")

    # Both observers received the same number of events.
    assert len(a) > 0
    assert len(a) == len(b)
    assert [e["type"] for e in a] == [e["type"] for e in b]
