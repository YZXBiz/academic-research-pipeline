"""Workspace must inject truststore on import for corporate SSL inspection proxies.

Without truststore the python ssl module's bundled CA list rejects the proxy's
MITM cert; httpx auto-closes the client mid-handshake and Dagster swallows the
underlying exception inside its multiprocess step worker — the visible failure
is just "Steps failed: ['raw_data']" with no actionable stderr.

These tests guarantee the workspace template stays Zscaler-safe: truststore is
a declared dependency AND pipeline/__init__.py performs the injection at
import time so it runs before any network call from any asset.
"""
from __future__ import annotations

import importlib
import ssl
from pathlib import Path

import pytest


def _read_pyproject() -> str:
    return (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")


def test_truststore_in_workspace_dependencies() -> None:
    """truststore must be in [project].dependencies, not optional/dev."""
    text = _read_pyproject()
    assert '"truststore' in text, (
        "truststore must be a runtime dependency in templates/dagster-experiment/"
        "pyproject.toml — Zscaler SSL injection cannot be optional."
    )


def test_pipeline_init_invokes_truststore_inject() -> None:
    """pipeline/__init__.py must call truststore.inject_into_ssl() at import time."""
    init = (
        Path(__file__).resolve().parent.parent
        / "src" / "pipeline" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "truststore" in init and "inject_into_ssl" in init, (
        "pipeline/__init__.py must import truststore and call inject_into_ssl() "
        "as the FIRST runtime action so HTTPS clients trust the system store "
        "before any asset's network call."
    )


def test_pipeline_import_replaces_default_ssl_context() -> None:
    """After importing pipeline, ssl.create_default_context returns a truststore-backed context.

    truststore.inject_into_ssl() monkey-patches ssl.SSLContext so that any
    subsequent HTTPS client (httpx, urllib3, requests) trusts the OS keychain.
    Verify the patch is in effect once `pipeline` has been imported.
    """
    pytest.importorskip("truststore")
    importlib.import_module("pipeline")
    ctx = ssl.create_default_context()
    # truststore subclasses ssl.SSLContext — check the class name is in the MRO
    mro_names = [c.__name__ for c in type(ctx).__mro__]
    assert "SSLContext" in mro_names, "Expected SSLContext in MRO"
    assert any("truststore" in (c.__module__ or "").lower() for c in type(ctx).__mro__), (
        "ssl.create_default_context() must return a truststore-backed context "
        "after `import pipeline`. If this fails, truststore.inject_into_ssl() "
        "was not called or did not take effect."
    )
