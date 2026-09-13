"""Production settings: rate limiting, CORS on errors, admin gating, startup checks."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.aws import database, handlers, queue
from backend.core import ratelimit
from backend.core.config import Settings, get_settings, production_problems


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    main.limiter.reset()
    yield
    get_settings.cache_clear()
    main.limiter.reset()


class TestLimiter:
    def test_allows_the_limit_then_blocks_until_the_window_moves(self):
        now = [0.0]
        limiter = ratelimit.SlidingWindowLimiter(window_seconds=60, clock=lambda: now[0])

        assert limiter.check("a", 2) is None
        assert limiter.check("a", 2) is None
        assert limiter.check("a", 2) == pytest.approx(60)
        assert limiter.check("b", 2) is None, "clients are limited separately"

        now[0] = 61
        assert limiter.check("a", 2) is None

    @pytest.mark.parametrize(
        "method, path, limited",
        [
            ("GET", "/api/recommendation/0xabc", True),
            ("GET", "/api/recommendation/0xabc/history", False),
            ("POST", "/api/simulate", True),
            ("POST", "/api/simulate/scenarios", True),
            ("GET", "/api/simulate/jobs/123", False),
            ("POST", "/api/chat", True),
            ("GET", "/api/history/0xabc/risk", True),
            ("GET", "/health", False),
            ("OPTIONS", "/api/chat", False),
        ],
    )
    def test_only_expensive_routes_are_limited(self, method, path, limited):
        assert ratelimit.is_limited(method, path) is limited

    def test_behind_a_proxy_only_the_appended_address_is_trusted(self):
        request = SimpleNamespace(
            headers={"x-forwarded-for": "6.6.6.6, 203.0.113.9"}, client=SimpleNamespace(host="10.0.0.5")
        )

        assert ratelimit.client_key(request, trust_proxy_headers=True) == "203.0.113.9"
        assert ratelimit.client_key(request, trust_proxy_headers=False) == "10.0.0.5"


class TestHttp:
    def test_the_limit_returns_429_with_cors_headers(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
        get_settings.cache_clear()
        client = TestClient(main.app)
        headers = {"Origin": "http://localhost:3000"}

        # An empty body fails validation, so nothing actually runs.
        codes = [client.post("/api/simulate", json={}, headers=headers).status_code for _ in range(3)]
        blocked = client.post("/api/simulate", json={}, headers=headers)

        assert codes == [422, 422, 429]
        assert blocked.headers["retry-after"]
        assert blocked.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_refresh_needs_the_admin_token_when_one_is_set(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
        get_settings.cache_clear()

        response = TestClient(main.app).post("/api/refresh/run", headers={"X-Admin-Token": "wrong"})

        assert response.status_code == 401

    def test_refresh_is_disabled_in_production_without_a_token(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("ADMIN_TOKEN", "")
        get_settings.cache_clear()

        assert TestClient(main.app).post("/api/refresh/run").status_code == 403


class TestProductionChecks:
    def test_unsafe_settings_are_reported(self):
        problems = production_problems(
            Settings(_env_file=None, cors_origins="*", aws_access_key_id="AKIA...", aws_secret_access_key="x")
        )

        assert len(problems) == 2

    def test_a_clean_production_config_passes(self):
        settings = Settings(_env_file=None, app_env="production", cors_origins="https://app.example.com")

        assert settings.is_production
        assert production_problems(settings) == []


class TestWorkerPlumbing:
    def test_received_jobs_are_hidden_for_longer_than_a_simulation_runs(self, monkeypatch):
        monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.example/q")
        get_settings.cache_clear()
        calls = []

        class FakeSqs:
            def receive_message(self, **kwargs):
                calls.append(kwargs)
                return {"Messages": []}

        monkeypatch.setattr(queue, "client", lambda service: FakeSqs())

        queue.receive_jobs(max_messages=5, wait_seconds=0)

        assert calls[0]["VisibilityTimeout"] == queue.JOB_VISIBILITY_SECONDS >= 900

    def test_a_lambda_invocation_loads_secrets_once_and_closes_the_pool(self, monkeypatch):
        from backend.aws import secrets

        loads, closes = [], []

        async def close():
            closes.append(1)

        monkeypatch.setattr(handlers, "_secrets_loaded", False)
        monkeypatch.setattr(secrets, "load_into_environment", lambda: loads.append(1))
        monkeypatch.setattr(database, "close", close)

        async def job():
            return {"ok": True}

        assert handlers._run(job()) == {"ok": True}
        assert handlers._run(job()) == {"ok": True}
        assert loads == [1], "secrets are read once per container"
        assert closes == [1, 1], "the pool never outlives an invocation's event loop"
