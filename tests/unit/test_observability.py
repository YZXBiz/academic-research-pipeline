"""Tests for observability module."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from academic_pipeline import observability


class TestConfigureSSL:
    def test_truststore_import_error(self):
        """When truststore is not installed, configure_ssl logs and continues."""
        with patch.dict("sys.modules", {"truststore": None}):
            importlib.reload(observability)
            observability.configure_ssl()


class TestConfigureObservability:
    def test_logfire_success_path(self):
        """When logfire is available, configure_observability wires httpx but
        leaves PydanticAI instrumentation to per-agent calls in
        runtime/trace_logger.py per PRD §6.13.T3."""
        mock_logfire = MagicMock()
        with patch.dict("sys.modules", {"logfire": mock_logfire}):
            observability.configure_observability()

        mock_logfire.configure.assert_called_once()
        mock_logfire.instrument_httpx.assert_called_once_with(capture_all=True)
        # Per §6.13.T3: global PydanticAI instrumentation is OFF; agents are
        # instrumented one-at-a-time inside traced_agent_run instead.
        mock_logfire.instrument_pydantic_ai.assert_not_called()


class TestTracingHealthStartupLine:
    """PRD §6.13.T2 — configure_observability emits a tracing-health line at
    startup carrying Logfire status (enabled/token-absent), project name
    (research-demo per OQ18), and dashboard URL hint.
    """

    def test_health_line_status_enabled_when_token_present(self, caplog) -> None:
        mock_logfire = MagicMock()
        with (
            patch.dict("sys.modules", {"logfire": mock_logfire}),
            patch.dict(
                "os.environ",
                {"LOGFIRE_TOKEN": "abc123"},
                clear=False,
            ),
            caplog.at_level("INFO"),
        ):
            observability.configure_observability()
        health_lines = [r for r in caplog.records if "tracing health" in r.getMessage()]
        assert health_lines, "expected a 'tracing health' log line at startup"
        msg = health_lines[0].getMessage()
        assert "status=enabled" in msg

    def test_health_line_status_token_absent_when_no_token(self, caplog) -> None:
        import os

        mock_logfire = MagicMock()
        env_no_token = {k: v for k, v in os.environ.items() if k != "LOGFIRE_TOKEN"}
        with (
            patch.dict("sys.modules", {"logfire": mock_logfire}),
            patch.dict(
                "os.environ",
                env_no_token,
                clear=True,
            ),
            caplog.at_level("INFO"),
        ):
            observability.configure_observability()
        health_lines = [r for r in caplog.records if "tracing health" in r.getMessage()]
        assert health_lines
        assert "status=token-absent" in health_lines[0].getMessage()

    def test_health_line_carries_project_name_per_oq18(self, caplog) -> None:
        mock_logfire = MagicMock()
        with patch.dict("sys.modules", {"logfire": mock_logfire}), caplog.at_level("INFO"):
            observability.configure_observability()
        health_lines = [r for r in caplog.records if "tracing health" in r.getMessage()]
        assert health_lines
        # OQ18: Logfire project stays "research-demo".
        assert "project=research-demo" in health_lines[0].getMessage()

    def test_health_line_includes_dashboard_url_hint(self, caplog) -> None:
        mock_logfire = MagicMock()
        with patch.dict("sys.modules", {"logfire": mock_logfire}), caplog.at_level("INFO"):
            observability.configure_observability()
        health_lines = [r for r in caplog.records if "tracing health" in r.getMessage()]
        assert health_lines
        assert "logfire-us.pydantic.dev" in health_lines[0].getMessage()


class TestCanonicalPhase2Observability:
    """Canonical four-test consolidation per PRD §6.13.T5.

    Each test exercises one of the four PRD-named coverage areas in a
    self-contained way. Underlying behaviors retain depth coverage in
    test_event_span_enrichment.py (8 tests) and
    test_trace_logger_per_agent_instrument.py (4 tests). This block is the
    single canonical reference satisfying the spec literal.
    """

    def test_degradation_when_no_token_no_exception(self, caplog) -> None:
        """PRD §6.13.T5 — configure_observability never raises when LOGFIRE_TOKEN
        is absent; pipeline runs normally with status=token-absent in the
        health line."""
        import os

        env_no_token = {k: v for k, v in os.environ.items() if k != "LOGFIRE_TOKEN"}
        with (
            patch.dict("os.environ", env_no_token, clear=True),
            caplog.at_level("INFO"),
        ):
            # Real logfire path (or absent) — no exception should escape
            observability.configure_observability()
        # Confirm the health line landed and reports the degraded mode
        health_lines = [r for r in caplog.records if "tracing health" in r.getMessage()]
        assert health_lines
        assert "status=token-absent" in health_lines[0].getMessage()

    def test_span_enrichment_for_cascade_verdict(self, tmp_path) -> None:
        """PRD §6.13.T1 — cascade_verdict event emits a parallel logfire.span
        carrying the same payload (incl. error_code per AP37)."""
        from academic_pipeline.runtime.events import EventLogger

        mock_span = MagicMock()
        logger = EventLogger(tmp_path)
        with patch("logfire.span", mock_span):
            logger.emit_sync(
                "cascade_verdict",
                stage="B",
                verdict="fail",
                score=0.42,
                reason="missing tokens",
                short_circuited=True,
                error_code="CAS001",
            )
        assert mock_span.called
        _, kwargs = mock_span.call_args
        # AP37: error_code present on the span so operators can correlate
        # Logfire searches against the on-disk events.jsonl record.
        assert kwargs.get("error_code") == "CAS001" or "CAS001" in str(kwargs)

    def test_per_agent_tag_present(self) -> None:
        """PRD §6.13.T3 — traced_agent_run instruments each agent so the
        resulting span carries the agent.name tag."""
        import asyncio
        from types import SimpleNamespace

        from academic_pipeline.runtime import trace_logger as tl

        agent = SimpleNamespace(name="canonical_test_agent")
        deps = SimpleNamespace(trace_logger=None)

        async def _run() -> None:
            await tl.traced_agent_run(agent, "ctx", deps=deps, name="n", phase="p")

        with (
            patch.object(tl, "_instrumented_agents", set()),
            patch("logfire.instrument_pydantic_ai") as mock_instrument,
            patch(
                "academic_pipeline.recovery.bounded_run.bounded_agent_run",
                return_value=SimpleNamespace(output="x"),
            ),
        ):
            asyncio.run(_run())
        mock_instrument.assert_called_once_with(agent)

    def test_logfile_handles_burst_writes(self, tmp_path) -> None:
        """PRD §6.13.T5 — events.jsonl is fsynced per record; a burst of
        50 writes preserves ordering and lands every record on disk
        without corruption."""
        from academic_pipeline.runtime.events import EventLogger

        logger = EventLogger(tmp_path)
        for i in range(50):
            logger.emit_sync(
                "stage_change",
                stage=f"s{i}",
                previous=f"s{i - 1}" if i else None,
            )
        # Schema-version marker (line 0) + 50 stage_change events.
        lines = (tmp_path / "events.jsonl").read_text().splitlines()
        assert len(lines) == 51
        # Ordering preserved: first stage is s0, last is s49.
        import json as _json

        first_event = _json.loads(lines[1])
        last_event = _json.loads(lines[50])
        assert first_event["stage"] == "s0"
        assert last_event["stage"] == "s49"
