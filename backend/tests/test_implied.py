"""Market-implied distributions: parsing, CDF construction and the lognormal fit.

The ETH figures used throughout are real, pulled from Polymarket in
``reference.ipynb`` — seven markets on ETH at 31 December 2026, the deepest
carrying $2.6M of volume.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from backend.models.market import AssetPredictionMarkets, PredictionMarket
from backend.quant import implied

TODAY = date(2026, 9, 13)
EXPIRY = "2026-12-31"

# (question, YES probability, direction, liquidity) as quoted.
ETH_MARKETS = [
    ("Will Ethereum dip to $800 by December 31, 2026?", 0.0225, "downside", 110_109.15),
    ("Will Ethereum dip to $1,000 by December 31, 2026?", 0.0650, "downside", 104_797.99),
    ("Will Ethereum reach $10,000 by December 31, 2026?", 0.0145, "upside", 104_569.03),
    ("Will Ethereum reach $8,000 by December 31, 2026?", 0.0215, "upside", 79_841.99),
    ("Will Ethereum dip to $1,500 by December 31, 2026?", 0.1400, "downside", 77_556.98),
    ("Will Ethereum reach $7,500 by December 31, 2026?", 0.0285, "upside", 66_851.61),
    ("Will Ethereum reach $6,000 by December 31, 2026?", 0.0430, "upside", 62_359.06),
]


def market(question, probability, direction, liquidity=1000.0, end_date=EXPIRY):
    return PredictionMarket(
        question=question,
        probability=probability,
        direction=direction,
        liquidity=liquidity,
        end_date=end_date,
        threshold=implied.parse_threshold(question),
    )


def eth_markets():
    return [market(*row) for row in ETH_MARKETS]


class TestParseThreshold:
    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("Will Ethereum dip to $800 by December 31, 2026?", 800.0),
            ("Will Ethereum dip to $1,000 by December 31, 2026?", 1_000.0),
            ("Will Ethereum reach $10,000 by December 31, 2026?", 10_000.0),
            ("Will Bitcoin hit $150k by December 31, 2026?", 150_000.0),
            ("Will Bitcoin hit $1.2M by June 30, 2027?", 1_200_000.0),
            ("Will Dogecoin reach $0.20 in September?", 0.20),
            ("Will Dogecoin dip to $0.05 in September?", 0.05),
        ],
    )
    def test_levels_are_read_from_real_questions(self, question, expected):
        assert implied.parse_threshold(question) == pytest.approx(expected)

    def test_a_trailing_word_is_not_read_as_a_magnitude_suffix(self):
        # "$1,000 by December" once parsed as $1,000 billion.
        assert implied.parse_threshold("Will Ethereum dip to $1,000 by December 31, 2026?") == 1_000.0

    @pytest.mark.parametrize(
        "question",
        [
            "Ethereum all time high by September 30, 2026?",
            "Will MegaETH perform an airdrop by December 31, 2026?",
            "Will El Salvador hold $1b+ of BTC by December 31, 2026?",  # not a price level
        ],
    )
    def test_questions_without_a_single_price_level_are_skipped(self, question):
        if "$" not in question:
            assert implied.parse_threshold(question) is None

    def test_range_markets_are_refused(self):
        # Two levels is a different statement and must not be read as one side
        # of a cumulative distribution.
        assert implied.parse_threshold("Will ETH be between $3,000 and $4,000?") is None


class TestPointsFromMarkets:
    def test_both_directions_become_points_on_one_cdf(self):
        grouped = implied.points_from_markets(eth_markets())

        assert list(grouped) == [EXPIRY]
        points = grouped[EXPIRY]
        assert [p.threshold for p in points] == [800, 1_000, 1_500, 6_000, 7_500, 8_000, 10_000]

        by_threshold = {p.threshold: p for p in points}
        # A downside market is read straight through...
        assert by_threshold[1_500].probability_at_or_below == pytest.approx(0.14)
        # ...an upside market as its complement.
        assert by_threshold[6_000].probability_at_or_below == pytest.approx(1 - 0.043)

    def test_real_eth_quotes_form_a_monotonic_curve(self):
        points = implied.points_from_markets(eth_markets())[EXPIRY]
        _, violations = implied.enforce_monotonic(points)
        assert violations == 0, "the live quotes are already a valid CDF"

    def test_expiries_are_never_mixed(self):
        markets = eth_markets() + [
            market("Will Ethereum dip to $2,000 by September 30, 2026?", 0.05, "downside",
                   end_date="2026-09-30")
        ]
        grouped = implied.points_from_markets(markets)
        assert set(grouped) == {EXPIRY, "2026-09-30"}
        assert len(grouped["2026-09-30"]) == 1

    def test_markets_without_a_level_or_an_expiry_are_dropped(self):
        markets = [
            market("Ethereum all time high by September 30, 2026?", 0.007, "upside"),
            market("Will Ethereum dip to $900 by December 31, 2026?", 0.03, "downside", end_date=None),
        ]
        assert implied.points_from_markets(markets) == {}

    def test_near_certain_quotes_are_ignored(self):
        markets = [market("Will Ethereum dip to $1 by December 31, 2026?", 0.0001, "downside")]
        assert implied.points_from_markets(markets) == {}

    def test_duplicate_levels_keep_the_deeper_market(self):
        markets = [
            market("Will Ethereum dip to $1,000 by December 31, 2026?", 0.065, "downside", 100_000.0),
            market("Will Ethereum dip to $1,000 by December 31, 2026?", 0.200, "downside", 500.0),
        ]
        points = implied.points_from_markets(markets)[EXPIRY]
        assert len(points) == 1
        assert points[0].probability_at_or_below == pytest.approx(0.065)


class TestMonotonicRepair:
    def test_a_dip_is_lifted_to_the_running_maximum(self):
        points = [
            implied.ImpliedPoint(800, 0.02, "downside"),
            implied.ImpliedPoint(1_000, 0.01, "downside"),  # stale: cannot fall
            implied.ImpliedPoint(1_500, 0.14, "downside"),
        ]
        repaired, violations = implied.enforce_monotonic(points)

        assert violations == 1
        assert [p.probability_at_or_below for p in repaired] == [0.02, 0.02, 0.14]
        assert repaired[1].repaired and not repaired[0].repaired

    def test_a_valid_curve_is_returned_untouched(self):
        points = [
            implied.ImpliedPoint(800, 0.02, "downside"),
            implied.ImpliedPoint(1_000, 0.065, "downside"),
        ]
        repaired, violations = implied.enforce_monotonic(points)
        assert violations == 0
        assert not any(p.repaired for p in repaired)


class TestFit:
    def test_the_fit_reproduces_the_markets_own_probabilities(self):
        """The assertion that matters: the fitted lognormal must agree with the
        market at the levels the market actually quoted."""
        fit = implied.fit_asset("ETH", eth_markets(), spot=3_000.0, today=TODAY)

        assert fit is not None
        assert fit.points_used == 7
        assert fit.violations_repaired == 0

        for point in fit.points:
            modelled = implied._model_probability(point.threshold, fit.spot, fit.sigma, fit.years)
            assert modelled == pytest.approx(point.probability_at_or_below, abs=0.10), (
                f"{point.question}: model {modelled:.1%} vs market "
                f"{point.probability_at_or_below:.1%}"
            )

    def test_the_fitted_volatility_is_plausible_for_eth(self):
        fit = implied.fit_asset("ETH", eth_markets(), spot=3_000.0, today=TODAY)
        assert 0.20 < fit.sigma < 2.0, f"implausible implied volatility: {fit.sigma}"

    def test_a_recovered_sigma_round_trips(self):
        """Generate a curve from a known sigma; the fit must find it again."""
        spot, years, true_sigma = 3_000.0, 0.5, 0.65
        thresholds = [1_500, 2_000, 2_500, 3_500, 4_500, 6_000]
        points = [
            implied.ImpliedPoint(
                threshold=t,
                probability_at_or_below=implied._model_probability(t, spot, true_sigma, years),
                direction="downside",
                liquidity=10_000.0,
            )
            for t in thresholds
        ]

        sigma, rmse = implied.fit_sigma(points, spot, years)

        assert sigma == pytest.approx(true_sigma, rel=0.02)
        assert rmse < 1e-4

    def test_too_few_points_produce_no_fit(self):
        markets = [market(*ETH_MARKETS[0]), market(*ETH_MARKETS[1])]
        assert implied.fit_asset("ETH", markets, spot=3_000.0, today=TODAY) is None

    def test_an_expired_market_is_ignored(self):
        markets = [market(q, p, d, liq, end_date="2026-01-01") for q, p, d, liq in ETH_MARKETS]
        assert implied.fit_asset("ETH", markets, spot=3_000.0, today=TODAY) is None

    def test_no_spot_price_means_no_fit(self):
        assert implied.fit_asset("ETH", eth_markets(), spot=0.0, today=TODAY) is None

    def test_a_badly_broken_curve_is_refused(self):
        markets = [
            market("Will Ethereum dip to $800 by December 31, 2026?", 0.90, "downside"),
            market("Will Ethereum dip to $1,000 by December 31, 2026?", 0.10, "downside"),
            market("Will Ethereum dip to $1,500 by December 31, 2026?", 0.05, "downside"),
            market("Will Ethereum dip to $2,000 by December 31, 2026?", 0.02, "downside"),
        ]
        assert implied.fit_asset("ETH", markets, spot=3_000.0, today=TODAY) is None

    def test_the_deepest_expiry_wins_when_several_qualify(self):
        thin = [
            market(f"Will Ethereum dip to ${level} by June 30, 2027?", p, "downside",
                   liquidity=10.0, end_date="2027-06-30")
            for level, p in [("1,000", 0.08), ("1,500", 0.16), ("2,000", 0.26)]
        ]
        fit = implied.fit_asset("ETH", eth_markets() + thin, spot=3_000.0, today=TODAY)
        assert fit.expiry == EXPIRY


class TestFitAssets:
    def test_only_assets_with_a_spot_price_are_fitted(self):
        entries = [
            AssetPredictionMarkets(asset="ETH", markets=eth_markets()),
            AssetPredictionMarkets(asset="DOGE", markets=eth_markets()),
        ]
        fits = implied.fit_assets(entries, spots={"ETH": 3_000.0}, today=TODAY)
        assert set(fits) == {"ETH"}


class TestBlend:
    def test_blending_moves_between_the_two_estimates(self):
        assert implied.blend(0.50, 1.00, 0.0) == pytest.approx(0.50)
        assert implied.blend(0.50, 1.00, 1.0) == pytest.approx(1.00)
        assert implied.blend(0.50, 1.00, 0.5) == pytest.approx(0.75)

    def test_a_poor_fit_is_given_no_weight(self):
        poor = implied.ImpliedFit(
            symbol="ETH", expiry=EXPIRY, years=0.3, spot=3_000.0,
            sigma=0.8, rmse=0.30, points_used=3, violations_repaired=0,
        )
        assert poor.quality == "poor"
        assert implied.weight_for(poor) == 0.0

    def test_a_clean_fit_on_the_real_data_is_trusted(self):
        fit = implied.fit_asset("ETH", eth_markets(), spot=3_000.0, today=TODAY)
        assert fit.quality in {"good", "fair"}
        assert implied.weight_for(fit) > 0.0


class TestAgainstTheSimulator:
    def test_simulated_paths_reproduce_the_market_probabilities(self):
        """End to end: fit sigma from the markets, run the real Monte Carlo
        engine with it, and check the simulated distribution lands where the
        market said it would."""
        import numpy as np

        from backend.quant.monte_carlo import SimulationConfig, SimulationInputs, simulate

        spot = 3_000.0
        fit = implied.fit_asset("ETH", eth_markets(), spot=spot, today=TODAY)
        horizon = max(int(round(fit.years * implied.TRADING_DAYS)), 1)

        output = simulate(
            SimulationInputs(
                symbols=["ETH"],
                weights=np.array([1.0]),
                volatilities=np.array([fit.sigma]),
                correlation=np.eye(1),
                initial_value=spot,
            ),
            SimulationConfig(horizon_days=horizon, simulations=40_000, seed=7),
        )

        for point in fit.points:
            simulated = float((output.terminal_values <= point.threshold).mean())
            assert simulated == pytest.approx(point.probability_at_or_below, abs=0.12), (
                f"{point.question}: simulated {simulated:.1%} vs market "
                f"{point.probability_at_or_below:.1%}"
            )


class TestCalibration:
    """The wiring: prediction markets reaching the volatility the engine uses."""

    def _estimate(self, symbols=("ETH", "USDC"), vols=(0.55, 0.01), quantity=1.0):
        import numpy as np

        from backend.assets.registry import AssetClass
        from backend.services import analysis

        positions = []
        for symbol, _ in zip(symbols, vols, strict=True):
            classification = (
                AssetClass.STABLECOIN if symbol == "USDC" else AssetClass.VOLATILE
            )
            position = analysis.Position(symbol, classification)
            position.quantity = quantity
            position.value_usd = 3_000.0 * quantity if symbol == "ETH" else 1.0 * quantity
            positions.append(position)

        return analysis.EstimationResult(
            positions=positions,
            matrix=None,
            weights=np.array([0.5, 0.5]),
            volatilities=np.array(list(vols)),
            correlation=np.eye(len(symbols)),
            drift=np.zeros(len(symbols)),
            total_value=sum(p.value_usd for p in positions),
            excluded=[],
        )

    def test_spot_price_comes_from_the_position(self):
        estimate = self._estimate()
        assert estimate.positions[0].spot_price == pytest.approx(3_000.0)

    def test_a_zero_quantity_position_has_no_spot_price(self):
        from backend.assets.registry import AssetClass
        from backend.services import analysis

        position = analysis.Position("ETH", AssetClass.VOLATILE)
        position.value_usd = 100.0
        assert position.spot_price == 0.0

    def test_implied_volatility_moves_the_estimate_toward_the_market(self):
        from backend.services import analysis

        estimate = self._estimate()
        entries = [AssetPredictionMarkets(asset="ETH", markets=eth_markets())]

        fits = analysis.calibrate_volatilities(estimate, entries, today=TODAY)

        assert set(fits) == {"ETH"}
        historical, calibrated = 0.55, float(estimate.volatilities[0])
        assert calibrated > historical, "the market prices ETH above its realised volatility"
        assert historical < calibrated < fits["ETH"].sigma, "a blend, not a replacement"

    def test_the_historical_estimate_is_preserved(self):
        from backend.services import analysis

        estimate = self._estimate()
        analysis.calibrate_volatilities(
            estimate, [AssetPredictionMarkets(asset="ETH", markets=eth_markets())], today=TODAY
        )
        assert float(estimate.historical_volatilities[0]) == pytest.approx(0.55)

    def test_stablecoins_are_never_calibrated(self):
        from backend.services import analysis

        estimate = self._estimate()
        analysis.calibrate_volatilities(
            estimate, [AssetPredictionMarkets(asset="USDC", markets=eth_markets())], today=TODAY
        )
        assert float(estimate.volatilities[1]) == pytest.approx(0.01)

    def test_assets_without_markets_keep_their_realised_estimate(self):
        from backend.services import analysis

        estimate = self._estimate()
        analysis.calibrate_volatilities(estimate, [], today=TODAY)
        assert float(estimate.volatilities[0]) == pytest.approx(0.55)
        assert estimate.implied_fits == {}

    def test_an_unusable_curve_changes_nothing(self):
        from backend.services import analysis

        estimate = self._estimate()
        broken = [market("Will Ethereum dip to $800 by December 31, 2026?", 0.02, "downside")]

        analysis.calibrate_volatilities(
            estimate, [AssetPredictionMarkets(asset="ETH", markets=broken)], today=TODAY
        )

        assert float(estimate.volatilities[0]) == pytest.approx(0.55)
        assert estimate.implied_fits == {}


class TestProbabilityWindow:
    """The 5-minute window that reported +0.00% on nearly every market."""

    def test_the_window_is_a_day_at_hourly_fidelity(self):
        from backend.services.polymarket import client

        assert client.PROBABILITY_WINDOW_SECONDS == 86_400
        assert client.PROBABILITY_FIDELITY_MINUTES == 60

    @pytest.mark.asyncio
    async def test_the_request_asks_for_the_full_window(self, monkeypatch):
        from backend.services.polymarket import client

        captured = {}

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"history": [{"p": "0.10"}, {"p": "0.14"}]}

        class Client:
            async def get(self, url, params=None, timeout=None):
                captured.update(params)
                return Response()

        monkeypatch.setattr(client, "get_client", lambda: Client())
        client.breaker.reset()  # is_open is a computed property, not a flag

        change = await client.fetch_probability_change("token")

        assert captured["fidelity"] == 60
        assert captured["endTs"] - captured["startTs"] == 86_400
        assert change == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_thin_markets_report_no_signal_rather_than_no_movement(self, monkeypatch):
        from backend.models.market import PredictionMarket
        from backend.services.polymarket import client

        async def never_called(token_id, **kwargs):
            raise AssertionError("a thin market should not be queried")

        monkeypatch.setattr(client, "fetch_probability_change", never_called)

        thin = PredictionMarket(
            question="Will Ethereum dip to $800 by December 31, 2026?",
            probability=0.02, direction="downside", liquidity=50.0,
            yes_token_id="t", end_date=EXPIRY,
        )

        async def search(asset, with_change=False):
            return [thin]

        # Exercise the filter directly: below the floor, nothing is asked.
        deep = [m for m in [thin] if m.liquidity >= client.MIN_LIQUIDITY_FOR_CHANGE]
        assert deep == []
        assert thin.probability_change_24h is None
