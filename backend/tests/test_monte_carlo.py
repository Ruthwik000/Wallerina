"""Tests for the Monte Carlo engine.

The statistical assertions compare against closed-form lognormal results, so
they check the simulation is actually correct rather than merely stable.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.quant.monte_carlo import (
    DriftMode,
    SimulationConfig,
    SimulationInputs,
    resolve_drift,
    simulate,
    simulate_allocation,
)
from backend.quant.risk import TRADING_DAYS

NORMAL_95 = 1.6448536269514722


def single_asset(volatility: float = 0.6, value: float = 100_000.0) -> SimulationInputs:
    return SimulationInputs(
        symbols=["ETH"],
        weights=np.array([1.0]),
        volatilities=np.array([volatility]),
        correlation=np.eye(1),
        initial_value=value,
    )


def three_assets(correlation: float) -> SimulationInputs:
    matrix = np.full((3, 3), correlation)
    np.fill_diagonal(matrix, 1.0)
    return SimulationInputs(
        symbols=["A", "B", "C"],
        weights=np.array([1 / 3, 1 / 3, 1 / 3]),
        volatilities=np.array([0.6, 0.7, 0.5]),
        correlation=matrix,
        initial_value=100_000.0,
    )


class TestValidation:
    def test_rejects_mismatched_weights(self):
        with pytest.raises(ValueError, match="weights"):
            SimulationInputs(
                symbols=["A", "B"],
                weights=np.array([1.0]),
                volatilities=np.array([0.5, 0.5]),
                correlation=np.eye(2),
                initial_value=1000.0,
            )

    def test_rejects_mismatched_correlation(self):
        with pytest.raises(ValueError, match="correlation"):
            SimulationInputs(
                symbols=["A", "B"],
                weights=np.array([0.5, 0.5]),
                volatilities=np.array([0.5, 0.5]),
                correlation=np.eye(3),
                initial_value=1000.0,
            )

    def test_rejects_impossible_config(self):
        with pytest.raises(ValueError):
            SimulationConfig(horizon_days=0)
        with pytest.raises(ValueError):
            SimulationConfig(simulations=1)
        with pytest.raises(ValueError):
            SimulationConfig(volatility_multiplier=0.0)


class TestDistribution:
    """Compare simulated moments against the analytic lognormal."""

    @pytest.fixture(scope="class")
    @staticmethod
    def output():
        return simulate(
            single_asset(),
            SimulationConfig(horizon_days=90, simulations=120_000, seed=42),
        )

    def test_zero_drift_preserves_expected_value(self, output):
        # Expected simple return is zero, so E[S_T] == S_0.
        assert output.expected_value == pytest.approx(100_000, rel=0.005)

    def test_median_matches_analytic(self, output):
        years = 90 / TRADING_DAYS
        expected = 100_000 * np.exp(-(0.6**2) * years / 2)
        assert output.median_value == pytest.approx(expected, rel=0.01)

    def test_percentiles_match_analytic(self, output):
        years = 90 / TRADING_DAYS
        drift = -(0.6**2) * years / 2
        spread = 0.6 * np.sqrt(years)

        assert output.p5 == pytest.approx(
            100_000 * np.exp(drift - spread * NORMAL_95), rel=0.02
        )
        assert output.p95 == pytest.approx(
            100_000 * np.exp(drift + spread * NORMAL_95), rel=0.02
        )

    def test_ordering_of_outcomes(self, output):
        assert output.worst_case <= output.p5 <= output.median_value
        assert output.median_value <= output.p95 <= output.best_case

    def test_probability_of_loss_is_a_probability(self, output):
        assert 0.0 <= output.probability_of_loss <= 1.0

    def test_shapes(self, output):
        assert output.terminal_values.shape == (120_000,)
        assert output.drawdowns.shape == (120_000,)
        assert len(output.percentiles[50]) == 91  # day 0 through day 90


class TestCorrelation:
    def test_correlated_book_is_riskier_than_independent(self):
        """The central claim of the product: correlation destroys diversification."""
        config = SimulationConfig(horizon_days=90, simulations=40_000, seed=7)

        correlated = simulate(three_assets(0.95), config)
        independent = simulate(three_assets(0.0), config)

        assert correlated.p5 < independent.p5
        assert correlated.expected_drawdown > independent.expected_drawdown

    def test_repairs_non_positive_definite_correlation(self):
        broken = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
        inputs = SimulationInputs(
            symbols=["A", "B", "C"],
            weights=np.array([1 / 3] * 3),
            volatilities=np.array([0.5, 0.5, 0.5]),
            correlation=broken,
            initial_value=100_000.0,
        )

        output = simulate(inputs, SimulationConfig(simulations=2_000, seed=1))

        assert np.isfinite(output.terminal_values).all()


class TestDrift:
    def test_zero_mode_is_minus_half_variance(self):
        inputs = single_asset(volatility=0.4)
        drift = resolve_drift(inputs, SimulationConfig(drift_mode=DriftMode.ZERO))
        assert drift[0] == pytest.approx(-0.5 * 0.4**2)

    def test_historical_mode_uses_supplied_drift(self):
        inputs = SimulationInputs(
            symbols=["A"],
            weights=np.array([1.0]),
            volatilities=np.array([0.4]),
            correlation=np.eye(1),
            initial_value=1000.0,
            historical_drift=np.array([0.25]),
        )
        drift = resolve_drift(inputs, SimulationConfig(drift_mode=DriftMode.HISTORICAL))
        assert drift[0] == pytest.approx(0.25)

    def test_shrunk_mode_lies_between(self):
        inputs = SimulationInputs(
            symbols=["A"],
            weights=np.array([1.0]),
            volatilities=np.array([0.4]),
            correlation=np.eye(1),
            initial_value=1000.0,
            historical_drift=np.array([0.25]),
        )
        drift = resolve_drift(
            inputs, SimulationConfig(drift_mode=DriftMode.SHRUNK, drift_shrinkage=0.25)
        )
        assert -0.5 * 0.4**2 < drift[0] < 0.25

    def test_falls_back_to_zero_without_history(self):
        inputs = single_asset(volatility=0.4)
        drift = resolve_drift(inputs, SimulationConfig(drift_mode=DriftMode.HISTORICAL))
        assert drift[0] == pytest.approx(-0.5 * 0.4**2)


class TestDeterminism:
    def test_same_seed_gives_identical_results(self):
        config = SimulationConfig(horizon_days=30, simulations=5_000, seed=99)
        first = simulate(single_asset(), config)
        second = simulate(single_asset(), config)

        np.testing.assert_array_equal(first.terminal_values, second.terminal_values)

    def test_different_seed_gives_different_results(self):
        base = SimulationConfig(horizon_days=30, simulations=5_000, seed=99)
        other = SimulationConfig(horizon_days=30, simulations=5_000, seed=100)

        assert not np.array_equal(
            simulate(single_asset(), base).terminal_values,
            simulate(single_asset(), other).terminal_values,
        )

    def test_results_cross_batch_boundaries_correctly(self):
        """Simulation count above the batch size must still be fully populated."""
        config = SimulationConfig(horizon_days=10, simulations=5_000, seed=3)
        output = simulate(single_asset(), config)

        assert output.terminal_values.shape == (5_000,)
        assert (output.terminal_values > 0).all()


class TestAntithetic:
    def test_reduces_variance_of_the_mean(self):
        def spread(antithetic: bool) -> float:
            means = [
                simulate(
                    single_asset(),
                    SimulationConfig(
                        horizon_days=90,
                        simulations=2_000,
                        seed=seed,
                        antithetic=antithetic,
                    ),
                ).expected_value
                for seed in range(25)
            ]
            return float(np.std(means))

        assert spread(True) < spread(False)


class TestDrawdown:
    def test_drawdown_is_a_fraction(self):
        output = simulate(
            single_asset(), SimulationConfig(horizon_days=60, simulations=5_000, seed=8)
        )
        assert (output.drawdowns >= 0).all()
        assert (output.drawdowns <= 1).all()

    def test_zero_volatility_has_no_drawdown(self):
        inputs = single_asset(volatility=0.0)
        output = simulate(inputs, SimulationConfig(simulations=1_000, seed=2))

        assert output.expected_drawdown == pytest.approx(0.0, abs=1e-12)
        assert output.terminal_values.std() == pytest.approx(0.0, abs=1e-6)


class TestAllocation:
    @pytest.fixture
    def book(self):
        return SimulationInputs(
            symbols=["ETH", "SOL", "USDC"],
            weights=np.array([0.5, 0.3, 0.2]),
            volatilities=np.array([0.6, 0.85, 0.01]),
            correlation=np.array([[1.0, 0.8, 0.0], [0.8, 1.0, 0.0], [0.0, 0.0, 1.0]]),
            initial_value=100_000.0,
        )

    def test_more_stablecoin_means_less_drawdown(self, book):
        mask = np.array([False, False, True])
        config = SimulationConfig(horizon_days=90, simulations=20_000, seed=3)

        drawdowns = [
            simulate_allocation(book, config, ratio, mask).expected_drawdown
            for ratio in (0.0, 0.25, 0.5, 0.75, 1.0)
        ]

        assert drawdowns == sorted(drawdowns, reverse=True)

    def test_target_ratio_is_actually_applied(self, book):
        mask = np.array([False, False, True])
        config = SimulationConfig(horizon_days=1, simulations=1_000, seed=1)

        # A fully stable book has almost no dispersion in outcomes.
        output = simulate_allocation(book, config, 1.0, mask)

        assert output.volatility_of_outcomes < 0.01

    def test_rejects_target_without_a_stable_asset(self, book):
        no_stables = np.array([False, False, False])
        with pytest.raises(ValueError, match="stable asset"):
            simulate_allocation(book, SimulationConfig(simulations=100), 0.5, no_stables)


class TestEdgeCases:
    def test_empty_portfolio_returns_empty_result(self):
        inputs = SimulationInputs(
            symbols=[],
            weights=np.zeros(0),
            volatilities=np.zeros(0),
            correlation=np.empty((0, 0)),
            initial_value=0.0,
        )
        output = simulate(inputs, SimulationConfig(simulations=1_000))

        assert output.simulations == 0
        assert output.terminal_values.size == 0

    def test_histogram_bins_cover_all_paths(self):
        output = simulate(
            single_asset(), SimulationConfig(horizon_days=30, simulations=5_000, seed=4)
        )
        bins = output.histogram(bins=20)

        assert len(bins) == 20
        assert sum(count for _, _, count in bins) == 5_000
