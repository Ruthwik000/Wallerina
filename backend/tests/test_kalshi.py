"""Kalshi client: the live response shapes, and the ladder as a distribution.

Every fixture is recorded from the real API, because three details of it
contradict the published documentation and an invented fixture would have
encoded the documentation's version.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.core.config import get_settings
from backend.models.market import AssetPredictionMarkets
from backend.quant import implied
from backend.services.kalshi import client as kalshi
from tests.fixtures import kalshi_btc_ladder as fixture

TODAY = date(2026, 9, 13)


@pytest.fixture(autouse=True)
def _reset_breaker():
    kalshi.breaker.reset()
    yield
    kalshi.breaker.reset()


class TestResponseShape:
    def test_prices_are_decimal_strings_not_integer_cents(self):
        """The bug this whole fixture exists to prevent.

        Every guide describes `yes_bid` as an integer 1-99. The live field is
        `yes_bid_dollars: "0.9400"`. Reading the documented shape would yield
        probabilities a hundredth of their real value, and nothing would raise.
        """
        market = next(m for m in fixture.LADDER if m["floor_strike"] == 70499.99)

        assert market["yes_bid_dollars"] == "0.9400"
        assert isinstance(market["yes_bid_dollars"], str)

        parsed = kalshi.to_prediction_market(market)
        assert 0.0 <= parsed.probability <= 1.0
        assert parsed.probability == pytest.approx(0.945)

    def test_a_greater_strike_reads_as_upside_at_its_floor(self):
        market = next(m for m in fixture.LADDER if m["floor_strike"] == 79999.99)
        parsed = kalshi.to_prediction_market(market)

        assert parsed.direction == "upside"
        assert parsed.threshold == pytest.approx(79999.99)
        assert parsed.source == "kalshi"
        assert parsed.end_date == "2026-09-18"

    def test_a_less_strike_reads_as_downside_at_its_cap(self):
        market = dict(fixture.LADDER[5])
        market.pop("floor_strike")
        market.update(strike_type="less", cap_strike=60000.0)

        parsed = kalshi.to_prediction_market(market)
        assert (parsed.direction, parsed.threshold) == ("downside", 60000.0)

    def test_a_range_strike_is_skipped(self):
        market = dict(fixture.LADDER[5])
        market.update(strike_type="between", floor_strike=70000.0, cap_strike=75000.0)
        assert kalshi.to_prediction_market(market) is None

    def test_status_must_be_active(self):
        """`status=open` returns an empty array from the live API; the value
        markets actually carry is "active"."""
        market = dict(fixture.LADDER[2], status="settled")
        assert kalshi.to_prediction_market(market) is None


class TestQualityFilters:
    def test_a_wide_spread_is_refused(self):
        """0.00/0.03 is the exchange shrugging, not a 1.5% probability."""
        market = dict(fixture.LADDER[2], yes_bid_dollars="0.0000", yes_ask_dollars="0.3000")
        assert kalshi.to_prediction_market(market) is None

    def test_a_strike_with_no_open_interest_is_refused(self):
        deep = next(m for m in fixture.LADDER if m["floor_strike"] == 86999.99)
        assert kalshi.to_prediction_market(deep) is None

    def test_a_crossed_book_is_refused(self):
        market = dict(fixture.LADDER[2], yes_bid_dollars="0.9500", yes_ask_dollars="0.9400")
        assert kalshi.to_prediction_market(market) is None

    def test_missing_prices_do_not_become_real_ones(self):
        market = dict(fixture.LADDER[2])
        market.pop("yes_bid_dollars")
        assert kalshi.to_prediction_market(market) is None

    def test_the_recorded_ladder_mostly_survives(self):
        kept = [m for m in (kalshi.to_prediction_market(x) for x in fixture.LADDER) if m]
        assert len(kept) >= 18, "the quality filters should not gut a healthy ladder"
        assert all(m.source == "kalshi" for m in kept)


class TestLadderAsDistribution:
    def _markets(self):
        return [m for m in (kalshi.to_prediction_market(x) for x in fixture.LADDER) if m]

    def test_the_ladder_forms_one_monotonic_cdf(self):
        grouped = implied.points_from_markets(self._markets())

        assert list(grouped) == ["2026-09-18"]
        points, violations = implied.enforce_monotonic(grouped["2026-09-18"])

        assert len(points) >= 18
        assert violations == 0, "a live strike ladder is already a valid CDF"
        assert points[0].threshold < points[-1].threshold

    def test_a_short_ladder_still_yields_an_annualised_volatility(self):
        """Option A, the day-one path: five days to expiry, annualised."""
        fit = implied.fit_asset("BTC", self._markets(), spot=77_000.0, today=TODAY)

        assert fit is not None
        assert fit.years == pytest.approx(5 / 365, rel=0.01)
        assert 0.10 < fit.sigma < 2.0, f"implausible annualised sigma: {fit.sigma}"
        assert fit.sources == ("kalshi",)

    def test_the_fit_reproduces_the_exchanges_own_prices(self):
        fit = implied.fit_asset("BTC", self._markets(), spot=77_000.0, today=TODAY)

        for point in fit.points:
            modelled = implied._model_probability(
                point.threshold, fit.spot, fit.sigma, fit.years
            )
            assert modelled == pytest.approx(point.probability_at_or_below, abs=0.12), (
                f"${point.threshold:,.0f}: model {modelled:.1%} vs market "
                f"{point.probability_at_or_below:.1%}"
            )


class TestHorizonSelection:
    """Option C: horizon-matched wins; a mismatched one is used but distrusted."""

    def _markets(self):
        return [m for m in (kalshi.to_prediction_market(x) for x in fixture.LADDER) if m]

    def test_a_short_ladder_read_at_a_long_horizon_is_marked_unmatched(self):
        fit = implied.fit_asset(
            "BTC", self._markets(), spot=77_000.0, today=TODAY, horizon_days=90
        )
        assert fit.horizon_matched is False

    def test_an_unmatched_fit_is_trusted_less(self):
        matched = implied.fit_asset(
            "BTC", self._markets(), spot=77_000.0, today=TODAY, horizon_days=5
        )
        unmatched = implied.fit_asset(
            "BTC", self._markets(), spot=77_000.0, today=TODAY, horizon_days=90
        )

        assert matched.horizon_matched is True

        # Discounted, not discarded: a mismatched ladder is still a market
        # price, and option C wants it as a working fallback.
        assert 0 < implied.weight_for(unmatched) < implied.weight_for(matched), (
            "annualising a 5-day ladder to 90 days assumes a flat term structure, "
            "but the fallback must still do something"
        )
        assert unmatched.quality == matched.quality, (
            "the horizon is a separate axis from how well the curve was fitted"
        )

    def test_a_horizon_matched_expiry_beats_a_deeper_mismatched_one(self):
        near = self._markets()

        far = []
        for market in fixture.LADDER:
            shifted = dict(market, expiration_time="2026-12-12T21:00:00Z")
            shifted["ticker"] = shifted["ticker"] + "-FAR"
            parsed = kalshi.to_prediction_market(shifted)
            if parsed is not None:
                parsed.liquidity = 1.0  # far dated and thin, as they usually are
                far.append(parsed)

        fit = implied.fit_asset(
            "BTC", near + far, spot=77_000.0, today=TODAY, horizon_days=90
        )

        assert fit.expiry == "2026-12-12", "horizon beats depth"
        assert fit.horizon_matched is True


class TestMergingExchanges:
    def test_points_from_both_exchanges_fit_one_curve(self):
        from tests.test_implied import eth_markets

        merged = implied.merge_sources(
            [AssetPredictionMarkets(asset="ETH", markets=eth_markets())],
            [AssetPredictionMarkets(asset="BTC", markets=[])],
        )
        assert [entry.asset for entry in merged] == ["ETH"]

    def test_one_asset_quoted_by_both_becomes_a_single_richer_curve(self):
        from tests.test_implied import eth_markets

        polymarket_side = [AssetPredictionMarkets(asset="ETH", markets=eth_markets())]
        kalshi_side = [
            AssetPredictionMarkets(
                asset="ETH",
                markets=[
                    m
                    for m in (kalshi.to_prediction_market(x) for x in fixture.LADDER)
                    if m
                ],
            )
        ]

        merged = implied.merge_sources(polymarket_side, kalshi_side)
        assert len(merged) == 1
        assert len(merged[0].markets) == len(eth_markets()) + len(kalshi_side[0].markets)

    def test_an_unreachable_exchange_contributes_nothing(self):
        from tests.test_implied import eth_markets

        only_one = implied.merge_sources(
            [AssetPredictionMarkets(asset="ETH", markets=eth_markets())], []
        )
        assert len(only_one[0].markets) == len(eth_markets())


class TestCircuitBreaker:
    def test_repeated_failures_open_the_breaker(self):
        settings = get_settings()
        assert kalshi.breaker.is_open is False

        for _ in range(settings.kalshi_failure_threshold):
            kalshi.breaker.record_failure()

        assert kalshi.breaker.is_open is True

    def test_success_closes_it(self):
        kalshi.breaker.record_failure()
        kalshi.breaker.record_success()
        assert kalshi.breaker.is_open is False


class TestSeriesMap:
    def test_every_asset_maps_to_verified_series_tickers(self):
        assert kalshi.ASSET_SERIES["BTC"][0] == "KXBTCD"
        for asset, series in kalshi.ASSET_SERIES.items():
            assert series, f"{asset} has no series"
            assert all(s.isupper() for s in series)

    def test_stablecoin_series_is_kept_out_of_the_price_map(self):
        """KXUSDTMIN prices a de-peg, not a price level. It must never reach a
        price distribution."""
        assert "USDT" not in kalshi.ASSET_SERIES
        assert kalshi.STABLECOIN_SERIES["USDT"] == "KXUSDTMIN"
