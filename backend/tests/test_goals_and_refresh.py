"""Saved goals, preset options, DSN handling and the background refresh."""

from __future__ import annotations

import asyncio

import pytest

from backend.agents import goal as goal_layer
from backend.aws import database, handlers
from backend.core.config import get_settings
from backend.services import refresh


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    database._memory_goals.clear()
    yield
    get_settings.cache_clear()
    database._memory_goals.clear()


class TestPresets:
    def test_every_preset_label_resolves_without_a_model(self):
        for option in goal_layer.preset_options():
            assert goal_layer.match_preset(option["label"]) == option["id"]

    def test_options_carry_rule_table_figures(self):
        balanced = next(o for o in goal_layer.preset_options() if o["id"] == "balanced")
        assert balanced["maximum_drawdown"] == goal_layer.PRESETS[goal_layer.GoalType.BALANCED]["maximum_drawdown"]


class TestGoals:
    @pytest.mark.asyncio
    async def test_goal_is_remembered_without_a_database(self):
        persisted = await database.save_goal("0xABCDEF0000000000000000000000000000000001", "Preserve capital")

        assert persisted is False
        saved = await database.get_goal("0xabcdef0000000000000000000000000000000001")
        assert saved["goal"] == "Preserve capital"
        assert saved["persisted"] is False

    @pytest.mark.asyncio
    async def test_unknown_wallet_has_no_goal(self):
        assert await database.get_goal("0x0000000000000000000000000000000000000009") is None


class TestDsn:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("postgresql+psycopg2://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
            ("postgresql+asyncpg://u:p@h/db", "postgresql://u:p@h/db"),
            ("  postgresql://u:p@h/db  ", "postgresql://u:p@h/db"),
            ("postgres://u:p@h/db", "postgres://u:p@h/db"),
        ],
    )
    def test_driver_suffix_is_removed(self, url, expected):
        assert database.normalise_dsn(url) == expected


class TestRefresh:
    @pytest.mark.asyncio
    async def test_one_failing_job_does_not_stop_the_others(self, monkeypatch):
        calls = []

        async def market():
            calls.append("market")
            return {"stored": 8}

        async def prediction():
            calls.append("prediction")
            raise RuntimeError("polymarket down")

        async def snapshots():
            calls.append("snapshots")
            return {"snapshots": 2}

        monkeypatch.setattr(handlers, "_refresh_market_data", market)
        monkeypatch.setattr(handlers, "_refresh_prediction_data", prediction)
        monkeypatch.setattr(handlers, "_snapshot_portfolios", snapshots)

        results = await refresh.run_once()

        assert calls == ["market", "prediction", "snapshots"]
        assert results["market_data"] == {"stored": 8}
        assert results["prediction_markets"] == {"error": "polymarket down"}
        assert refresh.status["last_result"] == results
        assert refresh.status["running"] is False

    @pytest.mark.asyncio
    async def test_disabled_refresh_starts_nothing(self, monkeypatch):
        monkeypatch.setenv("REFRESH_ENABLED", "false")
        get_settings.cache_clear()

        assert refresh.start() is None
        assert refresh.status["enabled"] is False

    @pytest.mark.asyncio
    async def test_loop_runs_on_the_interval_and_stops_cleanly(self, monkeypatch):
        monkeypatch.setenv("REFRESH_ENABLED", "true")
        monkeypatch.setenv("REFRESH_INTERVAL_MINUTES", "15")
        get_settings.cache_clear()

        runs = []

        async def fake_run_once():
            runs.append(1)
            return {}

        monkeypatch.setattr(refresh, "run_once", fake_run_once)

        task = refresh.start(initial_delay=0)
        await asyncio.sleep(0.05)
        await refresh.stop(task)

        assert runs == [1], "one run immediately, the next only after 15 minutes"
        assert refresh.status["interval_minutes"] == 15
