"""Tests for the keepalive httpx transport factory."""

from __future__ import annotations

import socket
from unittest.mock import patch

import httpx

from academic_pipeline.recovery.transport import (
    _tcp_keepalive_socket_options,
    make_keepalive_async_client,
)


def test_socket_options_always_includes_so_keepalive() -> None:
    opts = _tcp_keepalive_socket_options()
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in opts


def test_socket_options_on_macos_includes_tcp_keepalive() -> None:
    with patch("academic_pipeline.recovery.transport.platform.system", return_value="Darwin"):
        opts = _tcp_keepalive_socket_options()
    if hasattr(socket, "TCP_KEEPALIVE"):
        assert (socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 60) in opts


def test_socket_options_on_linux_includes_tcp_keepidle() -> None:
    with patch("academic_pipeline.recovery.transport.platform.system", return_value="Linux"):
        opts = _tcp_keepalive_socket_options()
    if hasattr(socket, "TCP_KEEPIDLE"):
        assert (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60) in opts


def test_socket_options_on_windows_falls_back_to_so_keepalive_only() -> None:
    with patch("academic_pipeline.recovery.transport.platform.system", return_value="Windows"):
        opts = _tcp_keepalive_socket_options()
    # Only SO_KEEPALIVE; no TCP_KEEPALIVE/TCP_KEEPIDLE since macOS/Linux constants don't apply
    assert opts == [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]


def test_make_keepalive_async_client_returns_async_client() -> None:
    client = make_keepalive_async_client()
    assert isinstance(client, httpx.AsyncClient)


def test_make_keepalive_async_client_uses_async_http_transport() -> None:
    client = make_keepalive_async_client()
    assert isinstance(client._transport, httpx.AsyncHTTPTransport)


def test_make_keepalive_async_client_respects_timeout() -> None:
    client = make_keepalive_async_client(timeout=42.0)
    assert client.timeout.read == 42.0
    assert client.timeout.write == 42.0
