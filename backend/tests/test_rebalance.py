"""The rebalance step: positions after the trades, and held-versus-target outcomes."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents import analysts, goal as goal_layer, judgement, pipeline
from backend.assets.registry import AssetClass
from backend.models.agents import Trade
from backend.models.goal import GoalType
from backend.models.market import MarketStress
from backend.models.quant import SimulationResult
from backend.services import analysis
from tests.test_allocation import decide

CONTEXT = goal_layer.context_for("0x" + "b" * 40, "balanced", goal_layer.preset_intent(GoalType.BALANCED))
NO_STRESS = MarketStress.model_construct(available=False, score=0.0)


def holding(symbol, value, classification):
    return SimpleNamespace(symbol=symbol, value_usd=value, classification=classification)


def book(*holdings):
    return SimpleNamespace(total_value_usd=sum(h.value_usd for h in holdings), holdings=list(holdings))


def simulated(ratio: float, drawdown: float = 0.2) -> SimulationResult:
    return SimulationResult.model_construct(
        horizon_days=90,
        stablecoin_ratio=ratio,
        expected_value=10_000.0,
        median_value=9_900.0,
        p5=7_000.0,
        p95=13_000.0,
        probability_of_loss=0.48,
        expected_drawdown=drawdown,
        max_drawdown_p95=drawdown * 2,
        expected_return=0.0,
        volatility_of_outcomes=0.3,
    )


class TestPositionsAfter:
    def test_without_trades_every_position_is_held(self):
        portfolio = book(
            holding("ETH", 6_000, AssetClass.VOLATILE),
            holding("USDC", 3_000, AssetClass.STABLECOIN),
            holding("BTC", 1_000, AssetClass.VOLATILE),
        )

        positions = analysts.positions_after(portfolio, [])

        assert [p.symbol for p in positions] == ["ETH", "USDC", "BTC"]
        assert {p.action for p in positions} == {"hold"}
        assert sum(p.ratio_after for p in positions) == pytest.approx(1.0)

    def test_trades_reduce_increase_and_remove_positions(self):
        portfolio = book(
            holding("ETH", 4_000, AssetClass.VOLATILE),
            holding("ETH", 2_000, AssetClass.VOLATILE),  # same symbol on another network
            holding("PEPE", 1_000, AssetClass.UNKNOWN),
            holding("BTC", 2_000, AssetClass.VOLATILE),
            holding("USDC", 1_000, AssetClass.STABLECOIN),
        )
        trades = [
            Trade(action="sell", symbol="PEPE", value_usd=1_000, reason="r"),
            Trade(action="sell", symbol="ETH", value_usd=3_000, reason="r"),
            Trade(action="buy", symbol="USDC", value_usd=4_000, reason="r"),
        ]

        positions = {p.symbol: p for p in analysts.positions_after(portfolio, trades)}

        assert "PEPE" not in positions, "a fully sold position is not held"
        assert (positions["ETH"].action, positions["ETH"].value_before_usd, positions["ETH"].value_after_usd) == ("reduce", 6_000, 3_000)
        assert (positions["USDC"].action, positions["USDC"].value_after_usd) == ("increase", 5_000)
        assert positions["BTC"].action == "hold"
        assert positions["USDC"].classification == "stablecoin"


class TestOutlook:
    def test_held_and_target_use_the_same_draws(self, monkeypatch):
        calls = []

        def run_simulation(estimate, initial, **kwargs):
            calls.append(kwargs)
            return simulated(kwargs.get("stablecoin_ratio"))

        monkeypatch.setattr(analysis, "run_simulation", run_simulation)
        estimate = SimpleNamespace(stable_mask=np.array([False, True]), stablecoin_ratio=0.1, total_value=10_000.0)
        decision = decide()

        outlook = pipeline._outlook(CONTEXT, estimate, NO_STRESS, decision)

        assert [c["stablecoin_ratio"] for c in calls] == [0.1, decision.target_stablecoin_ratio]
        assert calls[0]["seed"] == calls[1]["seed"]
        assert {c["horizon_days"] for c in calls} == {CONTEXT.horizon_days}
        assert outlook.current.stablecoin_ratio == 0.1
        assert outlook.target.stablecoin_ratio == decision.target_stablecoin_ratio

    def test_no_stable_leg_simulates_only_the_book_as_held(self, monkeypatch):
        calls = []

        def run_simulation(estimate, initial, **kwargs):
            calls.append(kwargs)
            return simulated(0.0)

        monkeypatch.setattr(analysis, "run_simulation", run_simulation)
        estimate = SimpleNamespace(stable_mask=np.array([False, False]), stablecoin_ratio=0.0, total_value=10_000.0)

        outlook = pipeline._outlook(CONTEXT, estimate, NO_STRESS, decide())

        assert len(calls) == 1 and "stablecoin_ratio" not in calls[0]
        assert outlook.target is None
        assert "no recognised stablecoin" in outlook.note

    def test_outlook_figures_reach_the_explainer_brief(self, monkeypatch):
        monkeypatch.setattr(analysis, "run_simulation", lambda e, i, **k: simulated(k.get("stablecoin_ratio"), 0.25))
        estimate = SimpleNamespace(stable_mask=np.array([True]), stablecoin_ratio=0.1, total_value=10_000.0)
        outlook = pipeline._outlook(CONTEXT, estimate, NO_STRESS, decide())

        brief = judgement.build_brief(CONTEXT, decide(), [], outlook)

        assert "MONTE CARLO EVIDENCE" in brief
        assert "As held (10.0% stablecoins): expected drawdown 25.0%" in brief
        assert "At target" in brief
