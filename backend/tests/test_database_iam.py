"""RDS IAM authentication: a fresh token for every physical connection."""

from __future__ import annotations

import pytest

from backend.aws import database
from backend.core.config import get_settings

HOST = "db.cluster-example.eu-north-1.rds.amazonaws.com"


@pytest.fixture(autouse=True)
def rds_settings(monkeypatch):
    monkeypatch.setenv("RDS_HOST", HOST)
    monkeypatch.setenv("RDS_PORT", "5432")
    monkeypatch.setenv("RDS_DATABASE", "wallerina")
    monkeypatch.setenv("RDS_USER", "wallerina_app")
    monkeypatch.setenv("AWS_REGION", "eu-north-1")
    get_settings.cache_clear()
    database._rds_client.cache_clear()
    monkeypatch.setattr(database, "_pool", None)
    yield
    get_settings.cache_clear()


def test_token_is_requested_for_the_configured_endpoint(monkeypatch):
    calls = []

    class FakeRds:
        def generate_db_auth_token(self, **kwargs):
            calls.append(kwargs)
            return "token"

    monkeypatch.setattr(database, "_rds_client", lambda: FakeRds())

    assert database.generate_auth_token() == "token"
    assert calls == [{"DBHostname": HOST, "Port": 5432, "DBUsername": "wallerina_app"}]


@pytest.mark.asyncio
async def test_every_new_connection_gets_a_fresh_token(monkeypatch):
    tokens = iter(["token-1", "token-2"])
    monkeypatch.setattr(database, "generate_auth_token", lambda: next(tokens))

    passwords = []

    async def fake_connect(*args, **kwargs):
        passwords.append(kwargs["password"])
        return object()

    monkeypatch.setattr(database.asyncpg, "connect", fake_connect)

    await database._iam_connect(host=HOST)
    await database._iam_connect(host=HOST)

    assert passwords == ["token-1", "token-2"]


@pytest.mark.asyncio
async def test_pool_uses_the_iam_hook_and_tls_and_no_password(monkeypatch):
    captured = {}

    async def fake_create_pool(*args, **kwargs):
        captured.update(kwargs, positional=args)
        return "pool"

    monkeypatch.setattr(database.asyncpg, "create_pool", fake_create_pool)

    assert await database.pool() == "pool"
    assert captured["connect"] is database._iam_connect
    assert captured["ssl"] == "require"
    assert (captured["host"], captured["port"], captured["database"], captured["user"]) == (
        HOST,
        5432,
        "wallerina",
        "wallerina_app",
    )
    assert "password" not in captured and "dsn" not in captured and captured["positional"] == ()


@pytest.mark.asyncio
async def test_unconfigured_database_reports_why(monkeypatch):
    monkeypatch.setenv("RDS_HOST", "")
    get_settings.cache_clear()

    assert await database.pool() is None
    result = await database.check()
    assert result["connected"] is False
    assert "RDS_HOST" in result["error"]
