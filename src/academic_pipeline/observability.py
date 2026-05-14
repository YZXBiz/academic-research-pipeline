"""Observability and SSL configuration."""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


# Shared keepalive httpx client cached at module scope so all 38+ Agent.from_file()
# constructions that fall through the patched SDK __init__ methods share a single
# connection pool instead of building one pool per agent.
_SHARED_KEEPALIVE_CLIENT: object | None = None


def _get_shared_keepalive_client() -> object:
    """Lazily construct one shared keepalive httpx.AsyncClient for all SDK instances.

    All 38+ Agent.from_file() constructions go through patched SDK __init__
    methods that fall back to this single client when no http_client is passed.
    Sharing one client = one connection pool = one set of keepalive sockets.
    """
    global _SHARED_KEEPALIVE_CLIENT
    if _SHARED_KEEPALIVE_CLIENT is None:
        from academic_pipeline.recovery.transport import make_keepalive_async_client

        _SHARED_KEEPALIVE_CLIENT = make_keepalive_async_client()
    return _SHARED_KEEPALIVE_CLIENT


def configure_ssl() -> None:
    """Inject system trust store for SSL verification.

    Uses the OS certificate store (macOS Keychain, Windows cert store) instead of Python's bundled certifi. Fixes
    proxy SSL interception (e.g. Zscaler) that breaks Python's default SSL.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
        logger.debug("truststore: using system certificate store")
    except ImportError:
        logger.debug("truststore not installed, using default certifi")


_LOGFIRE_PROJECT = "research-demo"  # OQ18 — Logfire project stays research-demo
_LOGFIRE_DASHBOARD_URL = f"https://logfire-us.pydantic.dev/yzxbiz/{_LOGFIRE_PROJECT}"


def configure_observability() -> None:
    """Configure Logfire for PydanticAI and httpx tracing.

    Silently skips if Logfire is unavailable or cannot connect.

    Emits a one-line "tracing health" startup record (PRD §6.13.T2) carrying
    Logfire status (`enabled` when LOGFIRE_TOKEN is set, `token-absent`
    otherwise), the project name (`research-demo` per OQ18), and a
    dashboard URL hint. The line lands in stdout/stderr logs and Logfire
    so operators can confirm tracing wiring at a glance.
    """
    import os

    try:
        import logfire

        logfire.configure(
            service_name="academic-pipeline",
            send_to_logfire="if-token-present",
        )
        # Per PRD §6.13.T3 the global instrument_pydantic_ai() call has been
        # replaced with per-agent instrumentation in
        # runtime/trace_logger.py::_instrument_agent_once so spans carry the
        # agent name. Only httpx stays globally instrumented here.
        logfire.instrument_httpx(capture_all=True)
        logger.info("Logfire observability configured")
    except Exception as e:
        logger.debug("Logfire unavailable, skipping: %s", e)

    status = "enabled" if os.environ.get("LOGFIRE_TOKEN") else "token-absent"
    logger.info(
        "tracing health: status=%s project=%s dashboard=%s",
        status,
        _LOGFIRE_PROJECT,
        _LOGFIRE_DASHBOARD_URL,
    )

    install_keepalive_provider_patch()
    install_deepseek_message_patch()


def install_keepalive_provider_patch() -> None:
    """Monkey-patch AsyncAnthropic + AsyncOpenAI to use a keepalive http_client by default.

    Without this, every Agent.from_file() construction creates SDK clients with
    httpx's defaults (no TCP keepalive). The LLM proxy then silently drops
    idle connections, leaving Python wedged in synchronous socket.recv() — the
    1h 43min hang documented in
    docs/superpowers/specs/2026-05-01-hang-recovery-design.md.
    """
    try:
        import anthropic
        import openai

        if not getattr(anthropic.AsyncAnthropic.__init__, "__keepalive_patched__", False):
            _orig_anthropic = anthropic.AsyncAnthropic.__init__

            def _patched_anthropic_init(self: object, *args: object, **kwargs: object) -> None:
                kwargs.setdefault("http_client", _get_shared_keepalive_client())
                _orig_anthropic(self, *args, **kwargs)

            _patched_anthropic_init.__keepalive_patched__ = True  # type: ignore[attr-defined]
            anthropic.AsyncAnthropic.__init__ = _patched_anthropic_init  # type: ignore[method-assign]

        if not getattr(openai.AsyncOpenAI.__init__, "__keepalive_patched__", False):
            _orig_openai = openai.AsyncOpenAI.__init__

            def _patched_openai_init(self: object, *args: object, **kwargs: object) -> None:
                kwargs.setdefault("http_client", _get_shared_keepalive_client())
                _orig_openai(self, *args, **kwargs)

            _patched_openai_init.__keepalive_patched__ = True  # type: ignore[attr-defined]
            openai.AsyncOpenAI.__init__ = _patched_openai_init  # type: ignore[method-assign]

        logger.info("Keepalive provider patch installed (or already present)")
    except ImportError as exc:
        logger.debug("Keepalive provider patch skipped (SDK not installed): %s", exc)


def install_deepseek_message_patch() -> None:
    """Monkey-patch OpenAIChatModel so thinking-only assistant turns are valid for DeepSeek.

    pydantic_ai's ``OpenAIChatModel._into_message_param`` sets ``content = None``
    for any assistant turn with no ``TextPart`` and no ``ToolCallPart`` — which
    happens on a thinking-only turn (reasoning went to the ``reasoning_content``
    field). OpenAI tolerates ``content: null``; DeepSeek's stricter validator
    rejects it with ``400 invalid_request_error: "Invalid assistant message:
    content or tool_calls must be set"``. This killed run-0511-2107 in the
    third pre-integrity round.

    This wraps ``_map_model_response`` so that when the mapped assistant
    message has ``content is None`` AND no ``tool_calls``, content is coerced
    to an empty string — satisfying DeepSeek's rule without changing meaning
    (the reasoning is still carried in ``reasoning_content``). Tool-call-only
    turns are left untouched: ``tool_calls`` already satisfies the constraint.
    """
    try:
        from pydantic_ai.models.openai import OpenAIChatModel

        if getattr(OpenAIChatModel._map_model_response, "__deepseek_patched__", False):
            return

        _orig_map = OpenAIChatModel._map_model_response

        def _patched_map_model_response(self: object, message: object) -> object:
            param = _orig_map(self, message)  # type: ignore[arg-type]
            if param.get("content") is None and not param.get("tool_calls"):
                param["content"] = ""
            return param

        _patched_map_model_response.__deepseek_patched__ = True  # type: ignore[attr-defined]
        OpenAIChatModel._map_model_response = _patched_map_model_response  # type: ignore[method-assign,assignment]
        logger.info("DeepSeek empty-message patch installed (or already present)")
    except ImportError as exc:
        logger.debug("DeepSeek message patch skipped (pydantic_ai not installed): %s", exc)


def shutdown_observability() -> None:
    """Flush and shut down all span exporters so no traces are lost on exit."""
    try:
        import logfire

        logfire.shutdown()
        logger.debug("Observability shut down")
    except Exception:
        pass


def _cancel_stale_workflows(db_path: str) -> None:
    """Cancel any PENDING workflows left over from a previous crashed run.

    DBOS.launch() blocks forever trying to recover PENDING workflows. If the previous process crashed mid-workflow,
    those workflows will never complete. Cancel them so launch doesn't hang.
    """
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        cancelled = conn.execute("UPDATE workflow_status SET status='CANCELLED' WHERE status='PENDING'").rowcount
        conn.commit()
        conn.close()
        if cancelled > 0:
            logger.info("Cancelled %d stale PENDING workflow(s) from previous run", cancelled)
    except Exception:
        pass


def init_dbos() -> bool:
    """Initialize DBOS (but don't launch yet).

    DBOS.launch() must be called AFTER all DBOSAgent instances are registered. Call launch_dbos() after Pipeline creates
    its agents.
    """
    try:
        from dbos import DBOS

        db_path = ".pipeline_runs/dbos.sqlite"
        _cancel_stale_workflows(db_path)

        DBOS(
            config={
                "name": "academic-pipeline",
                "system_database_url": f"sqlite:///{db_path}",
                "run_admin_server": False,
            }
        )
        logger.info("DBOS initialized (not yet launched)")
        return True
    except Exception as e:
        logger.debug("DBOS unavailable, skipping: %s", e)
        return False


def launch_dbos() -> None:
    """Launch DBOS after all agents are registered."""
    try:
        from dbos import DBOS

        DBOS.launch()
        logger.info("DBOS launched")
    except Exception as e:
        logger.debug("DBOS launch failed: %s", e)
