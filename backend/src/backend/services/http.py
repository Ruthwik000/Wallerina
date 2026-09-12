"""Shared async HTTP client.

One pooled client is created for the application's lifetime; every outbound
call goes through it so connection reuse and timeouts are consistent.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from backend.core.config import get_settings
from backend.services import dns

_client: httpx.AsyncClient | None = None


def create_client() -> httpx.AsyncClient:
    settings = get_settings()
    transport = httpx.AsyncHTTPTransport(
        limits=httpx.Limits(max_connections=settings.http_max_connections),
    )

    if settings.polymarket_dns_over_https:
        # httpx has no public hook for the network backend, so it is set on
        # the transport's connection pool (covered by tests/test_dns.py).
        transport._pool._network_backend = dns.OverrideBackend(
            hosts=[
                urlparse(settings.polymarket_gamma_url).hostname,
                urlparse(settings.polymarket_clob_url).hostname,
            ],
            resolver=dns.DohResolver(settings.dns_over_https_url),
        )

    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        transport=transport,
        headers={"accept": "application/json"},
    )


async def startup() -> bool:
    """Create the shared client. Returns whether this call created it.

    Jobs that may run inside the API (the background refresh) only shut the
    client down if they started it, so they never close the API's client.
    """
    global _client
    if _client is None:
        _client = create_client()
        return True
    return False


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialised; application startup did not run")
    return _client


class UpstreamError(RuntimeError):
    """An upstream provider failed or returned something unusable."""

    def __init__(self, provider: str, message: str, status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"{provider}: {message}")
