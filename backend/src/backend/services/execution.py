"""Execution: from a recommendation to swaps the user's wallet signs.

Wallerina never holds keys or sends transactions. This module turns the
recommendation's trades into concrete same-network swaps (a swap cannot move
value between chains) and prepares, for each, the transactions the wallet is
asked to sign: an exact-amount allowance where 0x needs one, and the swap.

Every 0x response is checked before anything reaches the wallet. An allowance
is only ever granted to AllowanceHolder, never for more than the swap sells,
and a transaction may never send more native token than the swap sells.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from backend.assets.registry import (
    CHAIN_IDS,
    NATIVE_TOKENS,
    STABLECOIN_DECIMALS,
    AssetClass,
    network_label,
    normalise_network,
    stablecoin_address,
)
from backend.core.config import get_settings
from backend.models.agents import Trade
from backend.models.execution import ExecutionLeg, LegQuote, PreparedTransaction
from backend.models.portfolio import Holding
from backend.services import swap

# Native balance left untouched so the wallet can still pay for gas, in USD.
GAS_RESERVE_USD: dict[str, float] = {
    "eth-mainnet": 25.0,
    "base-mainnet": 2.0,
    "arb-mainnet": 2.0,
    "matic-mainnet": 1.0,
}

# A swap this small costs more in gas and slippage than it moves, so the
# boundary is exclusive: a leg must be worth strictly more than this.
MIN_LEG_USD = 5.0

APPROVE_SELECTOR = "0x095ea7b3"  # approve(address,uint256)


class QuoteRejected(RuntimeError):
    """A quote that cannot or must not be executed. The message is user-facing."""


def _token(holding: Holding) -> str:
    return holding.contract_address or swap.NATIVE_TOKEN


def _base_units(usd: float, holding: Holding) -> int:
    """USD converted to the token's base units, never more than the wallet holds."""
    scale = Decimal(10) ** holding.decimals
    wanted = Decimal(str(usd)) / Decimal(str(holding.price_usd)) * scale
    held = Decimal(str(holding.quantity)) * scale
    return int(min(wanted, held).to_integral_value(rounding=ROUND_DOWN))


def _buy_target(holding: Holding, holdings: list[Holding]) -> tuple[str, str, int] | None:
    """(symbol, token, decimals) to swap a holding into, on the holding's own network."""
    network = holding.network
    same_network = [
        other
        for other in holdings
        if other.network == network
        and other.decimals is not None
        and _token(other).lower() != _token(holding).lower()
    ]

    if holding.classification is AssetClass.STABLECOIN:
        # Lowering the stable share: into the largest recognised volatile
        # position held here, or else the network's native token.
        volatile = [other for other in same_network if other.classification is AssetClass.VOLATILE]
        if volatile:
            best = max(volatile, key=lambda other: other.value_usd)
            return best.symbol, _token(best), best.decimals
        native = NATIVE_TOKENS.get(network)
        return (native[0], swap.NATIVE_TOKEN, native[2]) if native else None

    # Raising the stable share: a stablecoin already held here keeps issuers
    # unchanged; otherwise native USDC.
    stables = [other for other in same_network if other.classification is AssetClass.STABLECOIN]
    if stables:
        best = max(stables, key=lambda other: other.value_usd)
        return best.symbol, _token(best), best.decimals
    address = stablecoin_address(network, "USDC")
    return ("USDC", address, STABLECOIN_DECIMALS["USDC"]) if address else None


def build_legs(holdings: list[Holding], trades: list[Trade]) -> tuple[list[ExecutionLeg], list[str]]:
    """Turn the recommendation's sells into same-network swaps.

    Buys in the recommendation are not separate swaps: each sale is swapped
    straight into the right asset on its own network. A symbol's sales are
    taken from its largest positions first.
    """
    by_symbol: dict[str, list[Holding]] = {}
    for holding in sorted(holdings, key=lambda h: -h.value_usd):
        by_symbol.setdefault(holding.symbol, []).append(holding)

    # A symbol can appear in several sell trades (one per network it is held
    # on); they are pooled so no position is sold twice.
    to_sell: dict[str, tuple[float, str]] = {}
    for trade in trades:
        if trade.action == "sell":
            total, reason = to_sell.get(trade.symbol, (0.0, trade.reason))
            to_sell[trade.symbol] = (total + trade.value_usd, reason)

    legs: list[ExecutionLeg] = []
    skipped: list[str] = []

    for symbol, (remaining, reason) in to_sell.items():
        for holding in by_symbol.get(symbol, []):
            if remaining <= MIN_LEG_USD:
                break

            network = normalise_network(holding.network)
            chain = network_label(network)
            if network not in CHAIN_IDS:
                skipped.append(f"{symbol} on {chain}: execution is not supported on this network")
                continue
            if holding.decimals is None or holding.price_usd <= 0:
                skipped.append(f"{symbol} on {chain}: token decimals or price unknown")
                continue

            reserve = GAS_RESERVE_USD.get(network, 0.0) if holding.contract_address is None else 0.0
            amount_usd = min(remaining, holding.value_usd - reserve)
            if amount_usd <= MIN_LEG_USD:
                continue

            target = _buy_target(holding, holdings)
            if target is None:
                skipped.append(f"{symbol} on {chain}: nothing to swap into on this network")
                continue
            buy_symbol, buy_token, buy_decimals = target

            units = _base_units(amount_usd, holding)
            if units <= 0:
                continue

            sell_token = _token(holding)
            legs.append(
                ExecutionLeg(
                    id=f"{network}:{sell_token.lower()}:{buy_token.lower()}:{len(legs)}",
                    network=network,
                    chain=chain,
                    chain_id=CHAIN_IDS[network],
                    sell_symbol=symbol,
                    sell_token=sell_token,
                    sell_decimals=holding.decimals,
                    sell_amount=str(units),
                    sell_value_usd=round(amount_usd, 2),
                    buy_symbol=buy_symbol,
                    buy_token=buy_token,
                    buy_decimals=buy_decimals,
                    reason=reason,
                )
            )
            remaining -= amount_usd

        if remaining > MIN_LEG_USD:
            skipped.append(
                f"${remaining:,.0f} of the {symbol} sale has no executable position "
                "(gas reserve, unsupported network or dust)"
            )

    return legs, skipped


def approval(chain_id: int, token: str, spender: str, amount: int, kind: str, description: str) -> PreparedTransaction:
    """An ERC-20 approve(spender, amount) call."""
    data = APPROVE_SELECTOR + spender.lower().removeprefix("0x").rjust(64, "0") + format(amount, "064x")
    return PreparedTransaction(kind=kind, description=description, chain_id=chain_id, to=token, data=data, value="0x0")


def prepare_transactions(leg: ExecutionLeg, quote: dict, slippage_bps: int) -> LegQuote:
    """Check a 0x quote and turn it into the transactions to sign, in order."""
    route = f"{leg.sell_symbol} → {leg.buy_symbol} on {leg.chain}"
    sell_amount = int(leg.sell_amount)

    if not quote.get("liquidityAvailable"):
        raise QuoteRejected(f"0x found no liquidity for {route}")

    issues = quote.get("issues") or {}
    if issues.get("balance"):
        raise QuoteRejected(
            f"The wallet holds less {leg.sell_symbol} on {leg.chain} than this swap sells; prepare the trades again"
        )

    if int(quote.get("sellAmount") or sell_amount) > sell_amount:
        raise QuoteRejected(f"0x quoted a larger sale than requested for {route}; refusing it")

    transaction = quote.get("transaction") or {}
    if not transaction.get("to") or not transaction.get("data"):
        raise QuoteRejected(f"0x returned no transaction for {route}")

    native = leg.sell_token.lower() == swap.NATIVE_TOKEN.lower()
    value = int(transaction.get("value") or 0)
    if (native and value > sell_amount) or (not native and value != 0):
        raise QuoteRejected(f"0x's transaction for {route} would send more native token than the swap sells; refusing it")

    transactions: list[PreparedTransaction] = []

    allowance = issues.get("allowance")
    if allowance and not native:
        spender = str(allowance.get("spender") or "")
        if spender.lower() != swap.ALLOWANCE_HOLDER.lower():
            raise QuoteRejected("0x asked for an allowance on a contract other than AllowanceHolder; refusing to approve it")

        if int(allowance.get("actual") or 0) > 0:
            transactions.append(
                approval(
                    leg.chain_id,
                    leg.sell_token,
                    spender,
                    0,
                    "approve-reset",
                    f"Reset the existing {leg.sell_symbol} allowance (tokens such as USDT require it)",
                )
            )
        transactions.append(
            approval(
                leg.chain_id,
                leg.sell_token,
                spender,
                sell_amount,
                "approve",
                f"Allow 0x AllowanceHolder to spend exactly this swap's {leg.sell_symbol}",
            )
        )

    transactions.append(
        PreparedTransaction(
            kind="swap",
            description=f"Swap {leg.sell_symbol} for {leg.buy_symbol} on {leg.chain}",
            chain_id=leg.chain_id,
            to=transaction["to"],
            data=transaction["data"],
            value=hex(value),
        )
    )

    return LegQuote(
        leg_id=leg.id,
        chain_id=leg.chain_id,
        sell_amount=str(sell_amount),
        buy_amount=str(quote.get("buyAmount") or "0"),
        min_buy_amount=str(quote.get("minBuyAmount") or "0"),
        slippage_bps=slippage_bps,
        network_fee_wei=quote.get("totalNetworkFee"),
        transactions=transactions,
    )


async def quote_leg(leg: ExecutionLeg, taker: str) -> LegQuote:
    """A fresh quote for one leg, as signable transactions."""
    if CHAIN_IDS.get(normalise_network(leg.network)) != leg.chain_id:
        raise QuoteRejected("The trade's network and chain do not match")

    slippage_bps = get_settings().swap_slippage_bps
    quote = await swap.get_quote(
        chain_id=leg.chain_id,
        sell_token=leg.sell_token,
        buy_token=leg.buy_token,
        sell_amount=int(leg.sell_amount),
        taker=taker,
        slippage_bps=slippage_bps,
    )
    return prepare_transactions(leg, quote, slippage_bps)
