"""Tests for the risk engine."""

from __future__ import annotations

import numpy as np
import pytest

from backend.quant import risk


def series(values: list[float], start_day: int = 1) -> list[tuple[str, float]]:
    """Timestamped daily price series starting 2026-01-<start_day>."""
    return [
        (f"2026-01-{start_day + index:02d}T00:00:00Z", value)
        for index, value in enumerate(values)
    ]


class TestLogReturns:
    def test_computes_log_returns(self):
        result = risk.log_returns(np.array([100.0, 110.0, 121.0]))
        assert result.size == 2
        np.testing.assert_allclose(result, [np.log(1.1), np.log(1.1)])

    def test_short_series_yields_nothing(self):
        assert risk.log_returns(np.array([100.0])).size == 0

    def test_drops_non_positive_prices(self):
        result = risk.log_returns(np.array([100.0, 0.0, 110.0]))
        np.testing.assert_allclose(result, [np.log(1.1)])


class TestAlignHistories:
    def test_aligns_on_timestamps_not_position(self):
        """A gap mid-series must not slide one asset against another.

        This is the regression test for the bug where a provider omitting a
        single day silently destroyed the correlation estimate.
        """
        full = series([100.0, 110.0, 121.0, 133.1, 146.41])
        # Same asset, but the third observation is missing.
        gapped = [point for index, point in enumerate(full) if index != 2]

        matrix, dropped = risk.align_histories(
            {"A": full, "B": gapped}, min_coverage=0.5
        )

        assert dropped == []
        assert matrix.symbols == ["A", "B"]
        # Both columns describe the same price path, so on shared days the
        # returns must be identical and the correlation exactly 1.
        np.testing.assert_allclose(matrix.returns[:, 0], matrix.returns[:, 1])

    def test_drops_series_below_coverage(self):
        long_series = series([100.0 + i for i in range(20)])
        short_series = series([50.0, 51.0, 52.0], start_day=18)

        matrix, dropped = risk.align_histories(
            {"LONG": long_series, "SHORT": short_series}, min_coverage=0.6
        )

        assert dropped == ["SHORT"]
        assert matrix.symbols == ["LONG"]
        # The long history is preserved rather than truncated to three points.
        assert matrix.observations == 19

    def test_empty_input(self):
        matrix, dropped = risk.align_histories({})
        assert matrix.symbols == []
        assert dropped == []


class TestVolatility:
    def test_annualises_with_365_days(self):
        rng = np.random.default_rng(0)
        daily = 0.02
        returns = rng.normal(0, daily, size=(20_000, 1))

        result = risk.annualised_volatility(returns)

        assert result[0] == pytest.approx(daily * np.sqrt(365), rel=0.03)


class TestCorrelation:
    def test_recovers_known_correlation(self):
        rng = np.random.default_rng(1)
        target = np.array([[1.0, 0.7], [0.7, 1.0]])
        draws = rng.multivariate_normal([0, 0], target, size=50_000)

        result = risk.correlation_matrix(draws)

        assert result[0, 1] == pytest.approx(0.7, abs=0.02)

    def test_zero_variance_asset_is_identity_not_nan(self):
        returns = np.column_stack(
            [np.random.default_rng(2).normal(0, 0.01, 100), np.zeros(100)]
        )

        result = risk.correlation_matrix(returns)

        assert not np.isnan(result).any()
        assert result[1, 1] == 1.0
        assert result[0, 1] == 0.0


class TestNearestPositiveDefinite:
    def test_repairs_non_psd_matrix(self):
        # This matrix has a negative eigenvalue and fails Cholesky as-is.
        broken = np.array(
            [[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]]
        )
        assert np.linalg.eigvalsh(broken).min() < 0

        repaired = risk.nearest_positive_definite(broken)

        assert np.linalg.eigvalsh(repaired).min() >= 0
        np.testing.assert_allclose(np.diag(repaired), 1.0)
        np.linalg.cholesky(repaired)  # must not raise

    def test_leaves_valid_matrix_alone(self):
        valid = np.array([[1.0, 0.5], [0.5, 1.0]])
        np.testing.assert_allclose(risk.nearest_positive_definite(valid), valid)


class TestTailRisk:
    def test_var_is_positive_loss_fraction(self):
        returns = np.log1p(np.linspace(-0.20, 0.20, 1000))

        var = risk.historical_var(returns, confidence=0.95)

        assert 0 < var < 1
        assert var == pytest.approx(0.18, abs=0.01)

    def test_expected_shortfall_exceeds_var(self):
        rng = np.random.default_rng(3)
        returns = rng.normal(0, 0.03, 20_000)

        var = risk.historical_var(returns, 0.95)
        shortfall = risk.expected_shortfall(returns, 0.95)

        assert shortfall > var

    def test_max_drawdown(self):
        # 100 -> 120 -> 60 -> 90: worst decline is 50% from the peak of 120.
        prices = np.array([100.0, 120.0, 60.0, 90.0])
        returns = risk.log_returns(prices)

        assert risk.max_drawdown(returns) == pytest.approx(0.5)

    def test_drawdown_of_monotonic_rise_is_zero(self):
        returns = risk.log_returns(np.array([100.0, 110.0, 120.0]))
        assert risk.max_drawdown(returns) == pytest.approx(0.0)


class TestConcentration:
    def test_single_asset_is_one(self):
        assert risk.concentration(np.array([1.0])) == pytest.approx(1.0)

    def test_equal_weights_is_one_over_n(self):
        assert risk.concentration(np.array([0.25] * 4)) == pytest.approx(0.25)


class TestRiskContributions:
    def test_contributions_sum_to_one(self):
        rng = np.random.default_rng(4)
        returns = rng.normal(0, 0.02, (500, 3))
        weights = np.array([0.5, 0.3, 0.2])

        contributions, volatility = risk.risk_contributions(weights, returns)

        assert contributions.sum() == pytest.approx(1.0)
        assert volatility > 0

    def test_zero_weight_asset_contributes_nothing(self):
        rng = np.random.default_rng(5)
        returns = rng.normal(0, 0.02, (500, 2))

        contributions, _ = risk.risk_contributions(np.array([1.0, 0.0]), returns)

        assert contributions[1] == pytest.approx(0.0, abs=1e-12)


class TestBetas:
    def test_single_asset_beta_is_one(self):
        returns = np.random.default_rng(6).normal(0, 0.02, (300, 1))
        assert risk.betas(np.array([1.0]), returns)[0] == pytest.approx(1.0)
