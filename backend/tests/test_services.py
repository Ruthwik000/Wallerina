"""Tests for asset classification, portfolio construction and market parsing."""

from __future__ import annotations

import pytest

from backend.assets.registry import AssetClass, classify, is_spam_symbol, normalise_network
from backend.models.market import AssetPredictionMarkets, PredictionMarket
from backend.services.polymarket import client as polymarket
from backend.services.wallet import alchemy

USDC_ETH = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
UNI_ETH = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"


def token(
    *,
    network: str = "eth-mainnet",
    address: str | None = None,
    symbol: str | None = "TKN",
    decimals: int | None = 18,
    balance: str = "0x0de0b6b3a7640000",  # 1e18 == 1.0
    price: str | None = "100.0",
) -> dict:
    prices = [{"currency": "usd", "value": price}] if price is not None else []
    return {
        "network": network,
        "tokenAddress": address,
        "tokenBalance": balance,
        "tokenMetadata": {"symbol": symbol, "decimals": decimals, "name": symbol},
        "tokenPrices": prices,
    }


class TestClassification:
    def test_known_stablecoin_by_address(self):
        result, symbol = classify("eth-mainnet", USDC_ETH)
        assert result is AssetClass.STABLECOIN
        assert symbol == "USDC"

    def test_classification_is_case_insensitive(self):
        assert classify("eth-mainnet", USDC_ETH.lower())[0] is AssetClass.STABLECOIN

    def test_known_major_is_volatile(self):
        result, symbol = classify("eth-mainnet", UNI_ETH)
        assert result is AssetClass.VOLATILE
        assert symbol == "UNI"

    def test_native_token_is_volatile(self):
        result, symbol = classify("eth-mainnet", None)
        assert result is AssetClass.VOLATILE
        assert symbol == "ETH"

    def test_unknown_token_is_unknown_not_stable(self):
        """Specification section 9: never guess that something is a stablecoin."""
        result, symbol = classify("eth-mainnet", "0x" + "ab" * 20)
        assert result is AssetClass.UNKNOWN
        assert symbol is None

    def test_impersonating_symbol_is_not_trusted(self):
        """A token calling itself USDC at the wrong address stays unknown."""
        result, _ = classify("eth-mainnet", "0x" + "cd" * 20)
        assert result is not AssetClass.STABLECOIN

    def test_polygon_alias_is_normalised(self):
        assert normalise_network("polygon-mainnet") == "matic-mainnet"
        assert classify("polygon-mainnet", None)[1] == "POL"


class TestSpamDetection:
    @pytest.mark.parametrize(
        "symbol",
        [
            "Visit liquid-eth.org claim rewards",
            "www.symbiosis-finance.cc",
            "Telegram @vipTron888_bot",
            "AETH [ WWW.20ETH.EU ] Visit To claim reward",
            "Claim your bonus",
        ],
    )
    def test_rejects_advertising(self, symbol):
        assert is_spam_symbol(symbol)

    @pytest.mark.parametrize("symbol", ["ETH", "USDC", "WBTC", "wstETH", "USDC.e"])
    def test_accepts_real_symbols(self, symbol):
        assert not is_spam_symbol(symbol)

    def test_none_is_not_spam(self):
        assert not is_spam_symbol(None)


class TestBuildPortfolio:
    def test_decodes_hex_balance(self):
        portfolio = alchemy.build_portfolio("0xabc", [token(address=UNI_ETH)])

        assert portfolio.holdings[0].quantity == pytest.approx(1.0)
        assert portfolio.holdings[0].value_usd == pytest.approx(100.0)

    def test_native_metadata_comes_from_registry(self):
        """Alchemy returns nulls for native tokens; the registry fills them in."""
        native = token(address=None, symbol=None, decimals=None, price="2000.0")

        portfolio = alchemy.build_portfolio("0xabc", [native])

        holding = portfolio.holdings[0]
        assert holding.symbol == "ETH"
        assert holding.decimals == 18
        assert holding.value_usd == pytest.approx(2000.0)

    def test_drops_unpriced_tokens(self):
        portfolio = alchemy.build_portfolio("0xabc", [token(price=None)])
        assert portfolio.holdings == []

    def test_drops_dust(self):
        cheap = token(address=UNI_ETH, price="0.0000001")
        portfolio = alchemy.build_portfolio("0xabc", [cheap])
        assert portfolio.holdings == []

    def test_drops_spam_symbols(self):
        spam = token(symbol="Visit claim-rewards.io now", price="5.0")
        portfolio = alchemy.build_portfolio("0xabc", [spam])
        assert portfolio.holdings == []

    def test_drops_zero_balance(self):
        empty = token(address=UNI_ETH, balance="0x0")
        assert alchemy.build_portfolio("0xabc", [empty]).holdings == []

    def test_ratios_and_totals(self):
        tokens = [
            token(address=USDC_ETH, symbol="USDC", decimals=6, balance=hex(3_000_000), price="1.0"),
            token(address=UNI_ETH, price="7.0"),
        ]

        portfolio = alchemy.build_portfolio("0xabc", tokens)

        assert portfolio.total_value_usd == pytest.approx(10.0)
        assert portfolio.stablecoin_ratio == pytest.approx(0.3)
        assert portfolio.volatile_ratio == pytest.approx(0.7)
        assert sum(h.portfolio_ratio for h in portfolio.holdings) == pytest.approx(1.0)

    def test_unknown_counts_as_volatile_exposure(self):
        """An unrecognised asset must never be treated as safe."""
        tokens = [
            token(address=USDC_ETH, symbol="USDC", decimals=6, balance=hex(5_000_000), price="1.0"),
            token(address="0x" + "ef" * 20, symbol="MYSTERY", price="5.0"),
        ]

        portfolio = alchemy.build_portfolio("0xabc", tokens)

        assert portfolio.unknown_value_usd == pytest.approx(5.0)
        assert portfolio.volatile_ratio == pytest.approx(0.5)

    def test_empty_wallet(self):
        portfolio = alchemy.build_portfolio("0xabc", [])
        assert portfolio.total_value_usd == 0
        assert portfolio.stablecoin_ratio == 0

    def test_truncation_is_reported(self):
        portfolio = alchemy.build_portfolio("0xabc", [token(address=UNI_ETH)], True)
        assert portfolio.scan_truncated is True


class TestPolymarketParsing:
    def test_parses_json_string_fields(self):
        """Gamma returns these fields as JSON strings, not arrays."""
        market = {
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.14", "0.86"]',
            "clobTokenIds": '["111", "222"]',
        }

        token_id, probability = polymarket._extract_yes(market)

        assert token_id == "111"
        assert probability == pytest.approx(0.14)

    def test_handles_already_parsed_fields(self):
        market = {
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["0.4", "0.6"],
            "clobTokenIds": ["a", "b"],
        }
        assert polymarket._extract_yes(market) == ("a", pytest.approx(0.4))

    def test_handles_malformed_fields(self):
        assert polymarket._extract_yes({"outcomes": "not json"}) == (None, None)
        assert polymarket._extract_yes({}) == (None, None)

    def test_handles_missing_yes_outcome(self):
        market = {"outcomes": '["Up", "Down"]', "clobTokenIds": '["1", "2"]'}
        assert polymarket._extract_yes(market) == (None, None)

    @pytest.mark.parametrize(
        "question,expected",
        [
            ("Will Ethereum dip to $1,000 by December 31?", "downside"),
            ("Will Bitcoin fall below $50k?", "downside"),
            ("Will Ethereum reach $10,000 by December 31?", "upside"),
            ("Ethereum all time high by September 30?", "upside"),
            ("Will MegaETH perform an airdrop?", None),
        ],
    )
    def test_direction_detection(self, question, expected):
        assert polymarket._direction(question) == expected


class TestMarketStress:
    def make(self, markets):
        return [AssetPredictionMarkets(asset="ETH", markets=markets)]

    def test_no_markets_is_unavailable(self):
        stress = polymarket.compute_market_stress(self.make([]))

        assert stress.available is False
        assert stress.volatility_multiplier == 1.0

    def test_empty_input_is_unavailable(self):
        assert polymarket.compute_market_stress([]).available is False

    def test_high_downside_probability_raises_volatility(self):
        markets = [
            PredictionMarket(
                question="Will ETH dip to $1000?",
                probability=0.8,
                liquidity=100_000,
                direction="downside",
            )
        ]

        stress = polymarket.compute_market_stress(self.make(markets))

        assert stress.score == pytest.approx(0.8)
        assert stress.volatility_multiplier > 1.0
        assert stress.available is True

    def test_upside_markets_are_ignored(self):
        markets = [
            PredictionMarket(
                question="Will ETH reach $10000?",
                probability=0.9,
                liquidity=100_000,
                direction="upside",
            )
        ]

        stress = polymarket.compute_market_stress(self.make(markets))

        assert stress.markets_considered == 0
        assert stress.volatility_multiplier == 1.0

    def test_liquidity_weights_the_average(self):
        markets = [
            PredictionMarket(question="a", probability=0.9, liquidity=1_000_000, direction="downside"),
            PredictionMarket(question="b", probability=0.1, liquidity=1.0, direction="downside"),
        ]

        stress = polymarket.compute_market_stress(self.make(markets))

        # The deep market dominates.
        assert stress.score > 0.85

    def test_multiplier_is_bounded(self):
        markets = [
            PredictionMarket(question="a", probability=1.0, liquidity=1e9, direction="downside")
        ]

        stress = polymarket.compute_market_stress(self.make(markets), max_multiplier=1.5)

        assert stress.volatility_multiplier == pytest.approx(1.5)


class TestPriceFieldShapes:
    """Alchemy has shipped the price field in several shapes."""

    def test_standard_list_shape(self):
        assert alchemy._usd_price(token(price="12.5")) == pytest.approx(12.5)

    def test_dict_instead_of_list(self):
        record = token()
        record["tokenPrices"] = {"currency": "usd", "value": "7.0"}
        assert alchemy._usd_price(record) == pytest.approx(7.0)

    def test_alternate_key(self):
        record = token(price=None)
        record["prices"] = [{"currency": "usd", "value": "3.0"}]
        assert alchemy._usd_price(record) == pytest.approx(3.0)

    def test_missing_currency_defaults_to_usd(self):
        record = token()
        record["tokenPrices"] = [{"value": "9.0"}]
        assert alchemy._usd_price(record) == pytest.approx(9.0)

    def test_ignores_other_currencies(self):
        record = token()
        record["tokenPrices"] = [{"currency": "eur", "value": "9.0"}]
        assert alchemy._usd_price(record) is None

    def test_tolerates_junk(self):
        record = token()
        record["tokenPrices"] = ["nonsense", {"currency": "usd", "value": "bad"}]
        assert alchemy._usd_price(record) is None


class TestImpossibleBalances:
    def test_rejects_uint256_max(self):
        """The reference wallet holds a uint256-max scam position."""
        record = token(address=UNI_ETH, balance=hex(2**256 - 1))
        assert alchemy.build_portfolio("0xabc", [record]).holdings == []

    def test_rejects_absurd_supply(self):
        record = token(address=UNI_ETH, balance=hex(10**16 * 10**18))
        assert alchemy.build_portfolio("0xabc", [record]).holdings == []

    def test_keeps_plausible_large_holding(self):
        # 1,000,000 tokens is large but entirely ordinary.
        record = token(address=UNI_ETH, balance=hex(10**6 * 10**18), price="1.0")
        holdings = alchemy.build_portfolio("0xabc", [record]).holdings
        assert len(holdings) == 1
        assert holdings[0].quantity == pytest.approx(1_000_000)
