"""Cross-platform httpx.AsyncClient factory with TCP_KEEPALIVE socket options.

The LLM proxy and many other LB/NAT layers silently drop idle TCP
connections without sending FIN/RST. The default macOS keepidle is
7,200,000 ms (2 hours), and the default httpx read timeout doesn't help
because the SDK's SSE streaming path performs synchronous socket.recv()
under the async facade. Without keepalive, recv() blocks indefinitely.

Pattern adapted from shigechika/mcp-stdio PR #34 (Apr 2026), which solves
the same class of bug for MCP SSE streams.
"""

from __future__ import annotations

import platform
import socket

import httpx


_KEEPIDLE_S = 60
_KEEPINTVL_S = 15
_KEEPCNT = 4


def _tcp_keepalive_socket_options() -> list[tuple[int, int, int]]:
    """Return per-OS socket_options enabling TCP keepalive with ~120s detection.

    macOS 10.15+: TCP_KEEPALIVE (idle, secs) + TCP_KEEPINTVL + TCP_KEEPCNT
    Linux:        TCP_KEEPIDLE + TCP_KEEPINTVL + TCP_KEEPCNT
    Windows / other: SO_KEEPALIVE only (OS default probe interval, slower)
    """
    opts: list[tuple[int, int, int]] = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    system = platform.system()
    if system == "Darwin":
        if hasattr(socket, "TCP_KEEPALIVE"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, _KEEPIDLE_S))
        if hasattr(socket, "TCP_KEEPINTVL"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _KEEPINTVL_S))
        if hasattr(socket, "TCP_KEEPCNT"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _KEEPCNT))
    elif system == "Linux":
        if hasattr(socket, "TCP_KEEPIDLE"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, _KEEPIDLE_S))  # pyright: ignore[reportAttributeAccessIssue]
        if hasattr(socket, "TCP_KEEPINTVL"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _KEEPINTVL_S))
        if hasattr(socket, "TCP_KEEPCNT"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _KEEPCNT))
    return opts


def make_keepalive_async_client(*, timeout: float = 600.0) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient with TCP keepalive socket options applied.

    Pass the result to AnthropicProvider(http_client=...) or
    OpenAIProvider(http_client=...). Both pydantic-ai providers accept it
    and the underlying SDKs honor it (verified empirically against
    anthropic-sdk-python 0.96 and openai SDK).
    """
    transport = httpx.AsyncHTTPTransport(socket_options=_tcp_keepalive_socket_options())
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(connect=10.0, read=timeout, write=timeout, pool=10.0),
    )
