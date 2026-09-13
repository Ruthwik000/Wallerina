"""Execution: legs from trades, and the checks every 0x quote must pass."""

from __future__ import annotations

import pytest

from backend.assets.registry import AssetClass
from backend.core.config import get_settings
from backend.models.agents import Trade
from backend.models.execution import ExecutionLeg
from backend.models.portfolio import Holding
from backend.services import execution, swap

USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
USDC_ETH = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
DAI_ARB = "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1"
WETH_ETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
WETH_BASE = "0x4200000000000000000000000000000000000006"


def holding(symbol, network, value, *, contract=None, cls=AssetClass.VOLATILE, price=2000.0, decimals=18):
    return Holding(
        symbol=symbol,
        network=network,
        chain=network,
        contract_address=contract,
        quantity=value / price,
        price_usd=price,
        value_usd=value,
        portfolio_ratio=0.1,
        classification=cls,
        decimals=decimals,
    )


def sell(symbol, value):
    return Trade(action="sell", symbol=symbol, value_usd=value, reason=f"Reduce {symbol}")


class TestBuildLegs:
    def test_sales_become_same_network_swaps_into_stablecoins(self):
        holdings = [
            holding("ETH", "base-mainnet", 1_000),
            holding("ETH", "arb-mainnet", 500),
            holding("DAI", "arb-mainnet", 100, contract=DAI_ARB, cls=AssetClass.STABLECOIN, price=1.0),
        ]
        # Two sell trades for one symbol are pooled, not sold twice.
        trades = [sell("ETH", 1_000), sell("ETH", 400), Trade(action="buy", symbol="DAI", value_usd=1_400, reason="r")]

        legs, skipped = execution.build_legs(holdings, trades)

        assert skipped == []
        base, arbitrum = legs
        # Largest position first, keeping a $2 gas reserve of the native token.
        assert (base.network, base.chain_id, base.sell_token, base.sell_value_usd) == ("base-mainnet", 8453, swap.NATIVE_TOKEN, 998.0)
        assert base.sell_amount == str(499 * 10**15)
        assert (base.buy_symbol, base.buy_token, base.buy_decimals) == ("USDC", USDC_BASE, 6), "native USDC when no stable is held"
        assert (arbitrum.sell_value_usd, arbitrum.buy_symbol, arbitrum.buy_token) == (402.0, "DAI", DAI_ARB), "a held stable is preferred"

    def test_selling_stablecoins_buys_the_largest_volatile_position_or_native(self):
        holdings = [
            holding("USDC", "eth-mainnet", 1_000, contract=USDC_ETH, cls=AssetClass.STABLECOIN, price=1.0, decimals=6),
            holding("WETH", "eth-mainnet", 300, contract=WETH_ETH),
            holding("USDC", "base-mainnet", 600, contract=USDC_BASE, cls=AssetClass.STABLECOIN, price=1.0, decimals=6),
        ]

        legs, _ = execution.build_legs(holdings, [sell("USDC", 1_500)])

        ethereum, base = legs
        assert (ethereum.sell_amount, ethereum.buy_symbol, ethereum.buy_token) == (str(1_000 * 10**6), "WETH", WETH_ETH)
        assert (base.sell_value_usd, base.buy_symbol, base.buy_token) == (500.0, "ETH", swap.NATIVE_TOKEN)

    def test_unsupported_networks_unknown_decimals_and_leftovers_are_reported(self):
        holdings = [
            holding("OP", "opt-mainnet", 800, contract="0x4200000000000000000000000000000000000042"),
            holding("PEPE", "eth-mainnet", 400, contract="0x6982508145454ce325ddbe47a25d4ec3d2311933", cls=AssetClass.UNKNOWN, decimals=None),
            holding("ETH", "eth-mainnet", 30),
        ]

        legs, skipped = execution.build_legs(holdings, [sell("OP", 800), sell("PEPE", 400), sell("ETH", 30)])

        assert legs == [], "the $30 of ETH is inside the $25 mainnet gas reserve plus the $5 minimum"
        assert any("OP on Optimism: execution is not supported" in note for note in skipped)
        assert any("PEPE on Ethereum: token decimals" in note for note in skipped)
        assert any("of the ETH sale has no executable position" in note for note in skipped)

    def test_never_sells_more_than_the_wallet_holds(self):
        stale_price = holding("WETH", "base-mainnet", 1_000, contract=WETH_BASE)
        stale_price.quantity = 0.1  # the price moved: $1,000 at this price is 0.5 WETH, the wallet has 0.1

        legs, _ = execution.build_legs([stale_price], [sell("WETH", 1_000)])

        assert int(legs[0].sell_amount) == 10**17


LEG = ExecutionLeg(
    id="base-mainnet:weth:usdc:0",
    network="base-mainnet",
    chain="Base",
    chain_id=8453,
    sell_symbol="WETH",
    sell_token=WETH_BASE,
    sell_decimals=18,
    sell_amount="1000",
    sell_value_usd=10,
    buy_symbol="USDC",
    buy_token=USDC_BASE,
    buy_decimals=6,
    reason="r",
)
NATIVE_LEG = LEG.model_copy(update={"sell_symbol": "ETH", "sell_token": swap.NATIVE_TOKEN})
SETTLER = "0x" + "5" * 40


def quote(allowance=None, **overrides):
    body = {
        "liquidityAvailable": True,
        "sellAmount": "1000",
        "buyAmount": "990",
        "minBuyAmount": "980",
        "totalNetworkFee": "42",
        "issues": {"allowance": allowance, "balance": None},
        "transaction": {"to": SETTLER, "data": "0xdeadbeef", "value": "0", "gas": "150000"},
    }
    body.update(overrides)
    return body


class TestPrepareTransactions:
    def test_an_existing_allowance_needs_only_the_swap(self):
        result = execution.prepare_transactions(LEG, quote(), 100)

        assert [tx.kind for tx in result.transactions] == ["swap"]
        swap_tx = result.transactions[0]
        assert (swap_tx.to, swap_tx.data, swap_tx.value, result.min_buy_amount) == (SETTLER, "0xdeadbeef", "0x0", "980")

    def test_approval_is_exact_and_only_to_allowance_holder(self):
        result = execution.prepare_transactions(LEG, quote({"actual": "0", "spender": swap.ALLOWANCE_HOLDER}), 100)

        approve, swap_tx = result.transactions
        assert [approve.kind, swap_tx.kind] == ["approve", "swap"]
        assert approve.to == WETH_BASE
        assert approve.data == (
            "0x095ea7b3"
            + swap.ALLOWANCE_HOLDER.lower()[2:].rjust(64, "0")
            + format(1000, "064x")
        )

    def test_a_partial_allowance_is_reset_first(self):
        result = execution.prepare_transactions(LEG, quote({"actual": "5", "spender": swap.ALLOWANCE_HOLDER}), 100)

        assert [tx.kind for tx in result.transactions] == ["approve-reset", "approve", "swap"]
        assert result.transactions[0].data.endswith("0" * 64)

    @pytest.mark.parametrize(
        "leg, body, reason",
        [
            (LEG, quote({"actual": "0", "spender": SETTLER}), "other than AllowanceHolder"),
            (LEG, quote(liquidityAvailable=False), "no liquidity"),
            (LEG, quote(issues={"balance": {"actual": "1", "expected": "1000"}}), "holds less"),
            (LEG, quote(sellAmount="5000"), "larger sale"),
            (LEG, quote(transaction={"to": SETTLER, "data": "0x1", "value": "1"}), "more native token"),
            (NATIVE_LEG, quote(transaction={"to": SETTLER, "data": "0x1", "value": "1001"}), "more native token"),
            (LEG, quote(transaction={}), "no transaction"),
        ],
    )
    def test_unsafe_or_unusable_quotes_are_refused(self, leg, body, reason):
        with pytest.raises(execution.QuoteRejected, match=reason):
            execution.prepare_transactions(leg, body, 100)

    def test_native_sales_send_value_and_never_approve(self):
        body = quote({"actual": "0", "spender": swap.ALLOWANCE_HOLDER}, transaction={"to": SETTLER, "data": "0x1", "value": "1000"})

        result = execution.prepare_transactions(NATIVE_LEG, body, 100)

        assert [tx.kind for tx in result.transactions] == ["swap"]
        assert result.transactions[0].value == hex(1000)


class TestQuoteLeg:
    @pytest.mark.asyncio
    async def test_without_a_0x_key_execution_is_unavailable(self, monkeypatch):
        monkeypatch.setenv("ZEROEX_API_KEY", "")
        get_settings.cache_clear()
        try:
            with pytest.raises(swap.SwapUnavailable):
                await execution.quote_leg(LEG, taker="0x" + "a" * 40)
        finally:
            get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_a_leg_whose_chain_does_not_match_its_network_is_refused(self):
        with pytest.raises(execution.QuoteRejected, match="do not match"):
            await execution.quote_leg(LEG.model_copy(update={"chain_id": 1}), taker="0x" + "a" * 40)

    @pytest.mark.asyncio
    async def test_the_quote_request_carries_the_leg_and_slippage(self, monkeypatch):
        seen = {}

        async def fake_quote(**kwargs):
            seen.update(kwargs)
            return quote()

        monkeypatch.setattr(swap, "get_quote", fake_quote)

        result = await execution.quote_leg(LEG, taker="0x" + "a" * 40)

        assert seen["chain_id"] == 8453 and seen["sell_amount"] == 1000 and seen["taker"] == "0x" + "a" * 40
        assert result.slippage_bps == seen["slippage_bps"]
