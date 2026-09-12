"""Tests for the DNS-over-HTTPS override used for Polymarket.

No network: the DoH endpoint is an httpx MockTransport and the TCP layer is a
fake network backend that records where it was asked to connect.
"""

from __future__ import annotations

import httpcore
import httpx
import pytest

from backend.core.config import get_settings
from backend.services import dns, http


def doh_transport(answers: dict[str, list[str]], calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params["name"]
        if calls is not None:
            calls.append(name)
        return httpx.Response(
            200,
            json={"Answer": [{"name": name, "type": 1, "TTL": 300, "data": ip} for ip in answers.get(name, [])]},
        )

    return httpx.MockTransport(handler)


class FakeBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, unreachable: set[str] = frozenset()) -> None:
        self.unreachable = unreachable
        self.connected: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append(host)
        if host in self.unreachable:
            raise httpcore.ConnectTimeout("unreachable")
        return object()

    async def sleep(self, seconds):
        return None


class FailingResolver:
    async def resolve(self, host):
        raise httpx.ConnectError("DoH down")


class TestResolver:
    @pytest.mark.asyncio
    async def test_reads_a_records_and_caches(self):
        calls: list[str] = []
        resolver = dns.DohResolver(
            "https://doh.test/dns-query",
            transport=doh_transport({"gamma-api.polymarket.com": ["104.18.34.205"]}, calls),
        )

        assert await resolver.resolve("gamma-api.polymarket.com") == ["104.18.34.205"]
        assert await resolver.resolve("gamma-api.polymarket.com") == ["104.18.34.205"]
        assert calls == ["gamma-api.polymarket.com"]


class TestOverrideBackend:
    def resolver(self):
        return dns.DohResolver(
            "https://doh.test/dns-query",
            transport=doh_transport({"gamma-api.polymarket.com": ["104.18.34.205", "172.64.153.51"]}),
        )

    @pytest.mark.asyncio
    async def test_listed_host_connects_to_resolved_address(self):
        inner = FakeBackend()
        backend = dns.OverrideBackend(["gamma-api.polymarket.com"], self.resolver(), inner)

        await backend.connect_tcp("gamma-api.polymarket.com", 443)

        assert inner.connected == ["104.18.34.205"]

    @pytest.mark.asyncio
    async def test_other_hosts_use_system_dns(self):
        inner = FakeBackend()
        backend = dns.OverrideBackend(["gamma-api.polymarket.com"], self.resolver(), inner)

        await backend.connect_tcp("api.g.alchemy.com", 443)

        assert inner.connected == ["api.g.alchemy.com"]

    @pytest.mark.asyncio
    async def test_tries_the_next_address(self):
        inner = FakeBackend(unreachable={"104.18.34.205"})
        backend = dns.OverrideBackend(["gamma-api.polymarket.com"], self.resolver(), inner)

        await backend.connect_tcp("gamma-api.polymarket.com", 443)

        assert inner.connected == ["104.18.34.205", "172.64.153.51"]

    @pytest.mark.asyncio
    async def test_falls_back_to_hostname_when_doh_fails(self):
        inner = FakeBackend()
        backend = dns.OverrideBackend(["gamma-api.polymarket.com"], FailingResolver(), inner)

        await backend.connect_tcp("gamma-api.polymarket.com", 443)

        assert inner.connected == ["gamma-api.polymarket.com"]


class TestClientWiring:
    @pytest.fixture(autouse=True)
    def clean_settings(self):
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_polymarket_hosts_are_overridden_by_default(self, monkeypatch):
        monkeypatch.delenv("POLYMARKET_DNS_OVER_HTTPS", raising=False)
        client = http.create_client()
        try:
            backend = client._transport._pool._network_backend
            assert isinstance(backend, dns.OverrideBackend)
            assert backend._hosts == {"gamma-api.polymarket.com", "clob.polymarket.com"}
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_override_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("POLYMARKET_DNS_OVER_HTTPS", "false")
        client = http.create_client()
        try:
            assert not isinstance(client._transport._pool._network_backend, dns.OverrideBackend)
        finally:
            await client.aclose()
