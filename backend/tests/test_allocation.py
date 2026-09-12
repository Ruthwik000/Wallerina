"""Tests for the deterministic allocation engine and the goal layer.

This is the component specification section 2 protects: the allocation must be
computed, reproducible and bounded by the user's rules — never produced by a
model.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.agents.goal import (
    PRESETS,
    match_preset,
    preset_intent,
    rules_for,
)
from backend.models.goal import GoalType, PortfolioRules, RiskTolerance
from backend.quant import allocation


def rules(**overrides) -> PortfolioRules:
    base = {
        "risk_tolerance": RiskTolerance.MODERATE,
        "base_stablecoin_ratio": 0.40,
        "minimum_stablecoin_ratio": 0.25,
        "maximum_stablecoin_ratio": 0.70,
        "maximum_drawdown": 0.20,
        "rebalance_threshold": 0.10,
        "time_horizon_days": 90,
    }
    return PortfolioRules(**{**base, **overrides})


def decide(**overrides):
    args = {
        "rules": rules(),
        "current_stablecoin_ratio": 0.40,
        "annual_volatility": allocation.REFERENCE_VOLATILITY,
        "concentration": 0.20,
        "correlation": 0.30,
        "market_stress": None,
        "observations": 180,
    }
    return allocation.decide(**{**args, **overrides})


class TestBaseline:
    def test_neutral_environment_returns_the_goal_baseline(self):
        """With every signal at its reference, the goal's base ratio survives."""
        result = decide()
        assert result.target_stablecoin_ratio == pytest.approx(0.40, abs=0.01)

    def test_result_is_deterministic(self):
        assert decide().target_stablecoin_ratio == decide().target_stablecoin_ratio

    def test_every_driver_is_recorded(self):
        result = decide(annual_volatility=0.9, concentration=0.6, correlation=0.8)
        names = {driver.name for driver in result.drivers}

        assert "Goal baseline" in names
        assert "Realised volatility" in names
        assert "Concentration" in names
        assert "Correlation clustering" in names

    def test_drivers_reconstruct_the_target(self):
        """The recorded contributions must actually sum to the decision.

        If they don't, the explanation the judgement agent gives is a fiction.
        """
        result = decide(annual_volatility=0.75, concentration=0.5, correlation=0.7)
        total = sum(driver.contribution for driver in result.drivers)

        assert total == pytest.approx(result.target_stablecoin_ratio, abs=0.005)


class TestSignals:
    def test_higher_volatility_raises_the_target(self):
        calm = decide(annual_volatility=0.35).target_stablecoin_ratio
        wild = decide(annual_volatility=1.10).target_stablecoin_ratio
        assert wild > calm

    def test_volatility_shift_is_bounded(self):
        extreme = decide(annual_volatility=8.0, rules=rules(maximum_stablecoin_ratio=1.0))
        contribution = next(
            d.contribution for d in extreme.drivers if d.name == "Realised volatility"
        )
        assert contribution <= allocation.MAX_VOLATILITY_SHIFT + 1e-9

    def test_concentration_only_acts_above_threshold(self):
        below = decide(concentration=0.2)
        assert all(d.name != "Concentration" for d in below.drivers)

        above = decide(concentration=0.9)
        assert any(d.name == "Concentration" for d in above.drivers)

    def test_correlation_raises_the_target(self):
        loose = decide(correlation=0.1).target_stablecoin_ratio
        tight = decide(correlation=0.95).target_stablecoin_ratio
        assert tight > loose

    def test_market_stress_raises_the_target(self):
        calm = decide(market_stress=0.0).target_stablecoin_ratio
        stressed = decide(market_stress=0.9).target_stablecoin_ratio
        assert stressed > calm

    def test_missing_stress_is_not_treated_as_calm(self):
        """Absent data must lower confidence rather than imply a calm market."""
        assert decide(market_stress=None).confidence < decide(market_stress=0.0).confidence


class TestRuleBoundaries:
    def test_target_never_exceeds_the_goal_ceiling(self):
        result = decide(
            annual_volatility=5.0,
            concentration=1.0,
            correlation=1.0,
            market_stress=1.0,
            rules=rules(maximum_stablecoin_ratio=0.55),
        )
        assert result.target_stablecoin_ratio <= 0.55
        assert result.binding_constraint == "maximum_stablecoin_ratio"

    def test_target_never_falls_below_the_goal_floor(self):
        result = decide(
            annual_volatility=0.05,
            rules=rules(base_stablecoin_ratio=0.30, minimum_stablecoin_ratio=0.30),
        )
        assert result.target_stablecoin_ratio >= 0.30

    def test_band_stays_inside_the_rules(self):
        result = decide(rules=rules(minimum_stablecoin_ratio=0.35, maximum_stablecoin_ratio=0.45))
        low, high = result.acceptable_range

        assert low >= 0.35
        assert high <= 0.45
        assert low <= result.target_stablecoin_ratio <= high


class TestDrawdownConstraint:
    def test_drawdown_rule_can_raise_the_target(self):
        """A tight drawdown limit must override the signals, not be advisory."""

        # Drawdown falls linearly as the stable ratio rises.
        def probe(ratio: float) -> float:
            return 0.60 * (1 - ratio)

        result = decide(
            rules=rules(maximum_drawdown=0.12, maximum_stablecoin_ratio=1.0),
            drawdown_probe=probe,
        )

        assert result.target_stablecoin_ratio >= 0.79
        assert result.binding_constraint == "maximum_drawdown"
        assert result.drawdown_at_target <= 0.12 + 1e-6

    def test_satisfied_limit_does_not_move_the_target(self):
        result = decide(drawdown_probe=lambda ratio: 0.05)
        assert result.target_stablecoin_ratio == pytest.approx(0.40, abs=0.01)
        assert result.binding_constraint is None

    def test_unreachable_limit_does_not_loop_forever(self):
        """A limit no allocation can meet must terminate at full stables."""
        result = decide(
            rules=rules(maximum_drawdown=0.001, maximum_stablecoin_ratio=1.0),
            drawdown_probe=lambda ratio: 0.5,
        )
        assert result.target_stablecoin_ratio == pytest.approx(1.0)

    def test_probe_is_called_a_bounded_number_of_times(self):
        calls = []

        def probe(ratio: float) -> float:
            calls.append(ratio)
            return 0.60 * (1 - ratio)

        decide(
            rules=rules(maximum_drawdown=0.10, maximum_stablecoin_ratio=1.0),
            drawdown_probe=probe,
        )
        # Each probe is a simulation run, so the count must stay small.
        assert len(calls) <= 9


class TestRebalanceSignal:
    def test_no_rebalance_inside_the_band(self):
        result = decide(current_stablecoin_ratio=0.40)
        assert result.rebalance_required is False

    def test_rebalance_when_far_outside(self):
        result = decide(current_stablecoin_ratio=0.02)
        assert result.rebalance_required is True
        assert result.drift > 0

    def test_small_drift_does_not_trigger_churn(self):
        """Drift inside the threshold must not produce a trade."""
        result = decide(
            current_stablecoin_ratio=0.44, rules=rules(rebalance_threshold=0.10)
        )
        assert result.rebalance_required is False


class TestConfidence:
    def test_more_history_raises_confidence(self):
        assert decide(observations=30).confidence < decide(observations=180).confidence

    def test_confidence_is_a_probability(self):
        for observations in (0, 30, 180, 5000):
            assert 0.0 <= decide(observations=observations).confidence <= 1.0


class TestMeanPairwiseCorrelation:
    def test_excludes_stablecoins(self):
        """Stablecoins would drag the average down and hide a correlated book."""
        matrix = np.array(
            [
                [1.0, 0.9, 0.0],
                [0.9, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        stable = np.array([False, False, True])

        assert allocation.mean_pairwise_correlation(matrix, stable) == pytest.approx(0.9)
        assert allocation.mean_pairwise_correlation(matrix) < 0.9

    def test_single_asset_is_zero(self):
        assert allocation.mean_pairwise_correlation(np.eye(1)) == 0.0

    def test_empty_is_zero(self):
        assert allocation.mean_pairwise_correlation(np.empty((0, 0))) == 0.0


class TestGoalLayer:
    @pytest.mark.parametrize(
        "phrase,expected",
        [
            ("Preserve capital", GoalType.CAPITAL_PRESERVATION),
            ("preserve capital", GoalType.CAPITAL_PRESERVATION),
            ("Grow steadily", GoalType.GROWTH),
            ("Make heavy profit fast", GoalType.AGGRESSIVE_GROWTH),
            ("Save a lot over time", GoalType.SAVE_OVER_TIME),
            ("balanced", GoalType.BALANCED),
        ],
    )
    def test_presets_match_without_a_model(self, phrase, expected):
        assert match_preset(phrase) is expected

    def test_free_text_does_not_match_a_preset(self):
        assert match_preset("I want to buy a house in six months") is None

    def test_every_goal_type_has_a_preset_row(self):
        for goal_type in GoalType:
            assert goal_type in PRESETS

    def test_preset_rules_are_internally_consistent(self):
        for goal_type in GoalType:
            result = rules_for(preset_intent(goal_type))
            assert result.minimum_stablecoin_ratio <= result.base_stablecoin_ratio
            assert result.base_stablecoin_ratio <= result.maximum_stablecoin_ratio
            assert 0 < result.maximum_drawdown < 1

    def test_risk_tolerance_orders_the_baselines(self):
        aggressive = rules_for(preset_intent(GoalType.AGGRESSIVE_GROWTH))
        preservation = rules_for(preset_intent(GoalType.CAPITAL_PRESERVATION))

        assert aggressive.base_stablecoin_ratio < preservation.base_stablecoin_ratio
        assert aggressive.maximum_drawdown > preservation.maximum_drawdown

    def test_tight_drawdown_raises_the_floor(self):
        """Promising a 10% worst case while allowing 5% stables is incoherent."""
        intent = preset_intent(GoalType.AGGRESSIVE_GROWTH)
        intent.maximum_drawdown = 0.10

        assert rules_for(intent).minimum_stablecoin_ratio >= 0.40
