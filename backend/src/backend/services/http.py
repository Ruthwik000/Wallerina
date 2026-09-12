"""Shared async HTTP client.

One pooled client is created for the application's lifetime; every outbound
call goes through it so connection reuse and timeouts are consistent.
"""

from __future__ import annotations

import httpx

from backend.core.config import get_settings

_client: httpx.AsyncClient | None = None


def create_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        limits=httpx.Limits(max_connections=settings.http_max_connections),
        headers={"accept": "application/json"},
    )


async def startup() -> None:
    global _client
    if _client is None:
        _client = create_client()


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
