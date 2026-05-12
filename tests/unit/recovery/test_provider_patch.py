"""Test that install_keepalive_provider_patch causes Anthropic + OpenAI SDK
clients constructed without explicit http_client to use the keepalive transport.
"""

from __future__ import annotations

import httpx

from academic_pipeline.recovery.transport import make_keepalive_async_client


def test_keepalive_transport_has_socket_options() -> None:
    """Verify the transport our patch installs carries our socket_options.

    Defensive check — ensures the patched constructor receives a transport
    whose socket_options include SO_KEEPALIVE.
    """
    import socket

    client = make_keepalive_async_client()
    transport = client._transport
    assert isinstance(transport, httpx.AsyncHTTPTransport)
    # The internal pool's socket_options should contain SO_KEEPALIVE
    pool = transport._pool
    sock_opts = getattr(pool, "_socket_options", None)
    assert sock_opts is not None
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in sock_opts


def test_install_keepalive_provider_patch_is_re_entrant_safe() -> None:
    """Calling install_keepalive_provider_patch twice should not double-wrap.

    Without the sentinel guard, a second call captures the already-patched
    init as 'orig', so patched(patched(orig)) is created and every
    AsyncAnthropic() construction injects http_client twice via setdefault
    chains. The sentinel breaks that loop.
    """
    import anthropic

    from academic_pipeline.observability import install_keepalive_provider_patch

    install_keepalive_provider_patch()
    init_after_first = anthropic.AsyncAnthropic.__init__
    install_keepalive_provider_patch()
    init_after_second = anthropic.AsyncAnthropic.__init__

    # Same function object — second call was a no-op
    assert init_after_first is init_after_second
    assert getattr(init_after_second, "__keepalive_patched__", False) is True


def test_install_keepalive_provider_patch_shares_one_client_across_calls() -> None:
    """Multiple SDK instantiations should share the same httpx.AsyncClient."""
    import anthropic

    from academic_pipeline.observability import (
        _get_shared_keepalive_client,
        install_keepalive_provider_patch,
    )

    install_keepalive_provider_patch()
    c1 = anthropic.AsyncAnthropic(api_key="dummy")
    c2 = anthropic.AsyncAnthropic(api_key="dummy")
    # The shared client should be the same object across both constructions
    assert c1._client is c2._client
    # And it should equal the module's cached client
    assert c1._client is _get_shared_keepalive_client()
