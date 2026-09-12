"""DNS-over-HTTPS for hosts that local DNS misresolves.

Some ISPs answer lookups for blocked sites with a sinkhole address. Reliance Jio
does this for Polymarket: ``gamma-api.polymarket.com`` resolves to an address
that never accepts a connection, so every request dies with ConnectTimeout,
while the real Cloudflare addresses are reachable and fast.

For the configured hosts only, the address is resolved over HTTPS (Cloudflare,
by IP, so the lookup itself never touches local DNS) and the TCP connection is
opened to that address. TLS still uses the original hostname for SNI and
certificate verification, and the Host header is unchanged, so this is exactly
the connection the client would have made with honest DNS. Every other host
goes through the system resolver as usual.
"""

from __future__ import annotations

import asyncio
import logging
import time
import typing

import httpcore
import httpx

logger = logging.getLogger(__name__)

# DNS record type for IPv4 addresses.
A_RECORD = 1
MIN_TTL_SECONDS = 60


class DohResolver:
    """Resolves A records over DNS-over-HTTPS, caching by TTL."""

    def __init__(self, url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = url
        self._transport = transport
        self._cache: dict[str, tuple[list[str], float]] = {}
        self._lock = asyncio.Lock()

    async def resolve(self, host: str) -> list[str]:
        cached = self._cache.get(host)
        if cached and cached[1] > time.monotonic():
            return cached[0]

        async with self._lock:
            cached = self._cache.get(host)
            if cached and cached[1] > time.monotonic():
                return cached[0]

            async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
                response = await client.get(
                    self._url,
                    params={"name": host, "type": "A"},
                    headers={"accept": "application/dns-json"},
                )
                response.raise_for_status()
                answers = [
                    answer
                    for answer in response.json().get("Answer") or []
                    if answer.get("type") == A_RECORD
                ]

            addresses = [answer["data"] for answer in answers]
            if addresses:
                ttl = max(min(int(answer.get("TTL", 0)) for answer in answers), MIN_TTL_SECONDS)
                self._cache[host] = (addresses, time.monotonic() + ttl)
            return addresses


class OverrideBackend(httpcore.AsyncNetworkBackend):
    """Network backend that connects selected hosts to DoH-resolved addresses."""

    def __init__(
        self,
        hosts: typing.Iterable[str],
        resolver: DohResolver,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._hosts = {host.lower() for host in hosts if host}
        self._resolver = resolver
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        kwargs = {"timeout": timeout, "local_address": local_address, "socket_options": socket_options}

        if host.lower() in self._hosts:
            try:
                addresses = await self._resolver.resolve(host)
            except Exception as error:  # fall back to the system resolver
                logger.warning("DNS-over-HTTPS lookup failed for %s: %s", host, error)
                addresses = []

            for address in addresses:
                try:
                    return await self._inner.connect_tcp(address, port, **kwargs)
                except (httpcore.ConnectError, httpcore.ConnectTimeout) as error:
                    logger.debug("Could not connect to %s via %s: %s", host, address, error)

        return await self._inner.connect_tcp(host, port, **kwargs)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._inner.connect_unix_socket(path, timeout=timeout, socket_options=socket_options)

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)
