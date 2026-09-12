"""Alchemy client: wallet balances, current prices and price history.

Endpoints, payload shapes and response fields follow ``backend/reference.ipynb``
and were re-verified against the live API.

Two quirks of the portfolio endpoint drive most of the code here:

* Native tokens come back with a null contract address *and* null metadata, so
  symbol and decimals have to be supplied from the asset registry.
* A heavily airdropped wallet returns thousands of worthless spam tokens across
  many pages. Tokens without a price, without decimals, below a dust threshold,
  or whose symbol is really an advertisement are dropped before analysis.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backend.assets.registry import (
    AssetClass,
    NATIVE_TOKENS,
    classify,
    is_spam_symbol,
    network_label,
    normalise_network,
    price_symbol,
)
from backend.core.config import get_settings
from backend.models.market import PriceHistory, PricePoint
from backend.models.portfolio import ChainExposure, Holding, Portfolio
from backend.services.http import UpstreamError, get_client

logger = logging.getLogger(__name__)

PROVIDER = "alchemy"


def _ratio(part: float, whole: float) -> float:
    """Safe share of a total, clamped against floating-point overshoot."""
    if whole <= 0:
        return 0.0
    return min(max(part / whole, 0.0), 1.0)


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _usd_price(token: dict) -> float | None:
    """Read the USD price out of a token record.

    Alchemy has shipped this field under more than one key and in more than
    one shape, so the known variants are all tried rather than trusting a
    single path. Credit to ``validation.ipynb`` for catching this.
    """
    prices = token.get("tokenPrices") or token.get("prices") or []
    if isinstance(prices, dict):
        prices = [prices]

    for price in prices:
        if not isinstance(price, dict):
            continue
        currency = str(price.get("currency", "usd")).lower()
        if currency not in ("usd", "usd_price", ""):
            continue
        if (value := _to_float(price.get("value"))) is not None:
            return value

    return None


# A balance at or near the uint256 ceiling is not a holding, it is a scam
# contract advertising itself. Real supplies do not approach this.
UINT256_MAX = 2**256 - 1
ABSURD_QUANTITY = Decimal("1e15")


def _decode_balance(raw: str | None, decimals: int) -> float | None:
    """Convert a hex balance into a decimal quantity.

    Decimal keeps precision for the very large integers these tokens use; the
    result is only converted to float once it is back to a human scale.
    Structurally impossible balances are rejected outright.
    """
    if not raw:
        return None
    try:
        integer = int(raw, 16)
    except ValueError:
        return None
    if integer == 0 or integer == UINT256_MAX:
        return None

    quantity = Decimal(integer) / (Decimal(10) ** decimals)
    if quantity > ABSURD_QUANTITY:
        return None

    return float(quantity)


async def fetch_token_balances(
    address: str, networks: list[str] | None = None
) -> tuple[list[dict], bool]:
    """Page through Alchemy's tokens-by-address endpoint.

    Returns the raw token records and whether the scan hit the page limit
    before exhausting the wallet. Filtering and classification stay in one
    place (``build_portfolio``).
    """
    settings = get_settings()
    if not settings.alchemy_configured:
        raise UpstreamError(PROVIDER, "ALCHEMY_API_KEY is not set")

    url = f"{settings.alchemy_data_base_url}/{settings.alchemy_api_key}/assets/tokens/by-address"
    client = get_client()

    tokens: list[dict] = []
    page_key: str | None = None

    for _ in range(settings.portfolio_max_pages):
        payload: dict = {
            "addresses": [
                {
                    "address": address,
                    "networks": networks or settings.alchemy_networks,
                }
            ],
            "withMetadata": True,
            "withPrices": True,
            "includeNativeTokens": True,
            "includeErc20Tokens": True,
        }
        if page_key:
            payload["pageKey"] = page_key

        response = await client.post(url, json=payload)
        if response.status_code != 200:
            raise UpstreamError(
                PROVIDER,
                f"tokens/by-address returned {response.status_code}: {response.text[:200]}",
                response.status_code,
            )

        data = response.json().get("data") or {}
        tokens.extend(data.get("tokens") or [])

        page_key = data.get("pageKey")
        if not page_key:
            break
    else:
        # Loop exhausted without a break: more pages remain unread.
        logger.warning(
            "Stopped scanning %s after %s pages; wallet has more tokens",
            address,
            settings.portfolio_max_pages,
        )
        return tokens, True

    return tokens, False


def build_portfolio(
    address: str, tokens: list[dict], truncated: bool = False
) -> Portfolio:
    """Turn raw Alchemy token records into a classified, priced portfolio."""
    settings = get_settings()
    holdings: list[Holding] = []

    for token in tokens:
        network = normalise_network(token.get("network") or "")
        contract = token.get("tokenAddress")
        metadata = token.get("tokenMetadata") or {}

        classification, registry_symbol = classify(network, contract)

        # Native tokens carry no metadata; everything else must supply its own.
        if contract is None:
            native = NATIVE_TOKENS.get(network)
            if native is None:
                continue
            symbol, name, decimals = native
        else:
            symbol = registry_symbol or metadata.get("symbol")
            name = metadata.get("name")
            decimals = metadata.get("decimals")

        if not symbol or decimals is None:
            continue

        # Spam filtering. A token with no price is either worthless or unknown
        # to the pricing provider; either way it cannot be valued or simulated.
        if is_spam_symbol(metadata.get("symbol")) or is_spam_symbol(symbol):
            continue

        price = _usd_price(token)
        if price is None or price <= 0:
            continue

        quantity = _decode_balance(token.get("tokenBalance"), int(decimals))
        if quantity is None:
            continue

        value = quantity * price
        if value < settings.portfolio_min_usd_value:
            continue

        holdings.append(
            Holding(
                symbol=symbol,
                name=name,
                network=network,
                chain=network_label(network),
                contract_address=contract,
                quantity=quantity,
                price_usd=price,
                value_usd=value,
                portfolio_ratio=0.0,  # filled in below, once the total is known
                classification=classification,
                decimals=int(decimals),
            )
        )

    total = sum(holding.value_usd for holding in holdings)
    holdings.sort(key=lambda holding: holding.value_usd, reverse=True)

    for holding in holdings:
        holding.portfolio_ratio = _ratio(holding.value_usd, total)

    def class_total(asset_class: AssetClass) -> float:
        return sum(h.value_usd for h in holdings if h.classification is asset_class)

    stable = class_total(AssetClass.STABLECOIN)
    volatile = class_total(AssetClass.VOLATILE)
    unknown = class_total(AssetClass.UNKNOWN)

    by_network: dict[str, float] = {}
    for holding in holdings:
        by_network[holding.network] = by_network.get(holding.network, 0.0) + holding.value_usd

    chains = [
        ChainExposure(
            network=network,
            chain=network_label(network),
            value_usd=value,
            ratio=_ratio(value, total),
        )
        for network, value in sorted(by_network.items(), key=lambda item: -item[1])
    ]

    return Portfolio(
        address=address,
        total_value_usd=total,
        holdings=holdings,
        stablecoin_value_usd=stable,
        volatile_value_usd=volatile,
        unknown_value_usd=unknown,
        stablecoin_ratio=_ratio(stable, total),
        # Unrecognised assets are counted as volatile for exposure purposes:
        # treating an unknown token as safe is the one error that must not
        # happen (specification section 9).
        volatile_ratio=_ratio(volatile + unknown, total),
        concentration=sum(h.portfolio_ratio**2 for h in holdings),
        chains=chains,
        holdings_scanned=len(tokens),
        holdings_kept=len(holdings),
        scan_truncated=truncated,
    )


async def get_portfolio(address: str, networks: list[str] | None = None) -> Portfolio:
    tokens, truncated = await fetch_token_balances(address, networks)
    return build_portfolio(address, tokens, truncated)


async def fetch_price_history(
    *,
    symbol: str | None = None,
    network: str | None = None,
    contract_address: str | None = None,
    days: int | None = None,
    interval: str = "1d",
) -> PriceHistory:
    """Fetch daily price history by symbol, or by network and contract address.

    Alchemy requires ISO-8601 timestamps here; plain dates are rejected.
    """
    settings = get_settings()
    if not settings.alchemy_configured:
        raise UpstreamError(PROVIDER, "ALCHEMY_API_KEY is not set")

    days = days or settings.history_days
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    payload: dict = {
        "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval": interval,
    }

    if symbol:
        payload["symbol"] = price_symbol(symbol)
        label = payload["symbol"]
    elif network and contract_address:
        payload["network"] = normalise_network(network)
        payload["address"] = contract_address
        label = contract_address
    else:
        raise ValueError("fetch_price_history needs either a symbol or network+address")

    url = f"{settings.alchemy_prices_base_url}/{settings.alchemy_api_key}/tokens/historical"
    response = await get_client().post(url, json=payload)

    if response.status_code != 200:
        raise UpstreamError(
            PROVIDER,
            f"tokens/historical for {label} returned {response.status_code}",
            response.status_code,
        )

    body = response.json()
    points = [
        PricePoint(timestamp=point["timestamp"], value=value)
        for point in body.get("data") or []
        if (value := _to_float(point.get("value"))) is not None
    ]

    return PriceHistory(symbol=label, currency=body.get("currency", "usd"), points=points)


async def fetch_portfolio_history(
    holdings: list[Holding], days: int | None = None
) -> dict[str, PriceHistory]:
    """Fetch price history for every distinct holding, concurrently.

    Keyed by holding symbol. Assets whose history cannot be retrieved are
    omitted, and the caller decides how to treat them.
    """

    async def by_address(holding: Holding) -> PriceHistory | None:
        if not holding.contract_address:
            return None
        return await fetch_price_history(
            network=holding.network,
            contract_address=holding.contract_address,
            days=days,
        )

    async def one(holding: Holding) -> tuple[str, PriceHistory | None]:
        # Symbols are only trustworthy for registry-known assets. A spam or
        # unrecognised token may share a ticker with something completely
        # different, so those are priced by contract address only.
        trust_symbol = holding.classification is not AssetClass.UNKNOWN

        try:
            history = None

            if trust_symbol:
                try:
                    history = await fetch_price_history(symbol=holding.symbol, days=days)
                except UpstreamError as error:
                    logger.debug("Symbol lookup failed for %s: %s", holding.symbol, error)

            if history is None or len(history.points) < 2:
                history = await by_address(holding) or history

            return holding.symbol, history
        except (UpstreamError, ValueError) as error:
            logger.warning("No price history for %s: %s", holding.symbol, error)
            return holding.symbol, None

    # One request per distinct symbol. Where a symbol appears on several
    # chains, keep the largest position so any address fallback uses the most
    # liquid deployment.
    unique: dict[str, Holding] = {}
    for holding in sorted(holdings, key=lambda h: -h.value_usd):
        unique.setdefault(holding.symbol, holding)

    results = await asyncio.gather(*(one(holding) for holding in unique.values()))

    return {
        symbol: history
        for symbol, history in results
        if history is not None and len(history.points) >= 2
    }
