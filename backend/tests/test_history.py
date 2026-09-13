"""Backfilled performance and risk history, and the recorded-history queries."""

from __future__ import annotations

import math
from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.aws import database
from backend.core.config import get_settings
from backend.quant.risk import align_histories
from backend.services import history


def estimate_from_prices(prices: dict[str, list[float]], values: dict[str, float], excluded=()):
    length = len(next(iter(prices.values())))
    days = [f"2026-01-{day + 1:02d}" for day in range(length)]
    matrix, _ = align_histories(
        {symbol: [(f"{day}T00:00:00Z", price) for day, price in zip(days, series)] for symbol, series in prices.items()}
    )
    positions = [SimpleNamespace(symbol=symbol, value_usd=values[symbol]) for symbol in matrix.symbols]
    return SimpleNamespace(matrix=matrix, positions=positions, excluded=list(excluded))


def test_return_matrix_keeps_the_price_days():
    matrix, _ = align_histories(
        {"ETH": [("2026-01-01T00:00:00Z", 1.0), ("2026-01-02T00:00:00Z", 2.0), ("2026-01-03T00:00:00Z", 4.0)]}
    )

    assert matrix.days == ("2026-01-01", "2026-01-02", "2026-01-03")
    assert matrix.observations == 2


def test_backfill_values_todays_holdings_at_past_prices():
    # ETH quadrupled while USDC stayed flat: $400 of ETH today was $100 two days ago.
    estimate = estimate_from_prices({"ETH": [1, 2, 4], "USDC": [1, 1, 1]}, {"ETH": 400, "USDC": 100}, excluded=["PEPE"])

    days, values = history.backfilled_values(estimate)
    result = history.performance(estimate, [{"t": "2026-01-03T10:00:00+00:00", "value_usd": 512.0}])

    assert days == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert values == pytest.approx([200, 300, 500])
    assert result.total_return == pytest.approx(1.5)
    assert result.window_days == 2
    assert result.recorded[0].v == 512.0
    assert result.excluded == ["PEPE"]


def test_rolling_volatility_and_drawdown():
    prices = [100, 110, 99, 120, 90, 95]
    estimate = estimate_from_prices({"ETH": prices}, {"ETH": 95})

    result = history.risk_history(estimate, [], window=3)

    returns = np.diff(np.log(prices))
    assert len(result.volatility) == len(returns) - 3 + 1
    assert result.volatility[0].t == "2026-01-04"
    assert result.volatility[0].v == pytest.approx(np.std(returns[:3], ddof=1) * math.sqrt(365), abs=1e-4)
    assert [point.v for point in result.drawdown] == pytest.approx(
        [0, 0, 1 - 99 / 110, 0, 1 - 90 / 120, 1 - 95 / 120], abs=1e-4
    )


def test_no_history_gives_empty_series():
    estimate = SimpleNamespace(
        matrix=SimpleNamespace(observations=0, days=(), returns=np.empty((0, 0)), n_assets=0),
        positions=[],
        excluded=[],
    )

    assert history.performance(estimate, []).total_return is None
    assert history.risk_history(estimate, []).volatility == []


def test_bucket_width_keeps_charts_small():
    assert database.history_bucket(1) == timedelta(minutes=5)
    assert database.history_bucket(30) == timedelta(days=30) / database.HISTORY_MAX_POINTS


@pytest.mark.asyncio
async def test_recorded_history_is_empty_without_a_database(monkeypatch):
    monkeypatch.setenv("RDS_HOST", "")
    get_settings.cache_clear()
    try:
        assert await database.portfolio_value_history("0x" + "1" * 40, 30) == []
        assert await database.risk_metrics_history("0x" + "1" * 40, 30) == []
    finally:
        get_settings.cache_clear()
