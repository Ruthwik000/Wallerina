"""Polymarket client: prediction-market probabilities for held assets.

Endpoints and response shapes follow ``backend/reference.ipynb``:

* ``GET {gamma}/public-search``  — find active events matching a query
* ``GET {gamma}/events``         — browse active events
* ``GET {clob}/prices-history``  — price (probability) history for a YES token

Gamma returns ``outcomes``, ``outcomePrices`` and ``clobTokenIds`` as JSON
*strings* rather than arrays, so every one of those fields is parsed defensively.

The YES price of a binary market is read as the market's implied probability.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from backend.core.config import get_settings
from backend.models.market import (
    AssetPredictionMarkets,
    MarketStress,
    PredictionMarket,
)
from backend.quant import implied
from backend.services.http import UpstreamError, get_client

logger = logging.getLogger(__name__)

PROVIDER = "polymarket"

# Search terms per asset, plus the pattern a market's text must match to count
# as genuinely about that asset. The pattern guards against false positives —
# searching "ether" alone also returns unrelated markets.
ASSET_QUERIES: dict[str, tuple[tuple[str, ...], re.Pattern[str]]] = {
    "BTC": (("bitcoin",), re.compile(r"\bbitcoin\b|\bbtc\b", re.I)),
    "ETH": (("ethereum", "ether"), re.compile(r"\bethereum\b|\bether\b|\beth\b", re.I)),
    "SOL": (("solana",), re.compile(r"\bsolana\b|\bsol\b", re.I)),
    "DOGE": (("dogecoin",), re.compile(r"\bdogecoin\b|\bdoge\b", re.I)),
    "XRP": (("xrp", "ripple"), re.compile(r"\bxrp\b|\bripple\b", re.I)),
    "ARB": (("arbitrum",), re.compile(r"\barbitrum\b", re.I)),
    "OP": (("optimism",), re.compile(r"\boptimism\b", re.I)),
    "POL": (("polygon",), re.compile(r"\bpolygon\b|\bmatic\b", re.I)),
    "AVAX": (("avalanche",), re.compile(r"\bavalanche\b|\bavax\b", re.I)),
    "BNB": (("bnb", "binance"), re.compile(r"\bbnb\b|\bbinance\b", re.I)),
    "ADA": (("cardano",), re.compile(r"\bcardano\b|\bada\b", re.I)),
    "SUI": (("sui",), re.compile(r"\bsui\b", re.I)),
    "LINK": (("chainlink",), re.compile(r"\bchainlink\b|\blink\b", re.I)),
    "UNI": (("uniswap",), re.compile(r"\buniswap\b", re.I)),
    "PEPE": (("pepe",), re.compile(r"\bpepe\b", re.I)),
    "SHIB": (("shiba",), re.compile(r"\bshiba\b|\bshib\b", re.I)),
    "CAKE": (("pancakeswap",), re.compile(r"\bpancakeswap\b", re.I)),
}

# Questions resolving on a fall are the ones that carry downside information.
DOWNSIDE_PATTERN = re.compile(r"\bdip\b|\bfall\b|\bdrop\b|\bbelow\b|\bcrash\b|\bdown to\b", re.I)
UPSIDE_PATTERN = re.compile(r"\breach\b|\bhit\b|\babove\b|\ball time high\b|\bexceed\b", re.I)

MAX_MARKETS_PER_ASSET = 10


class _CircuitBreaker:
    """Stops hammering an unreachable provider.

    Polymarket is blocked outright on some networks. Without a breaker every
    analysis pays the full timeout on every query, which added ~16 seconds to
    each request during development.
    """

    def __init__(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        if self._open_until and time.monotonic() < self._open_until:
            return True
        if self._open_until:
            # Cooldown elapsed: allow traffic through again.
            self._open_until = 0.0
            self._failures = 0
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        settings = get_settings()
        self._failures += 1
        if self._failures >= settings.polymarket_failure_threshold:
            self._open_until = time.monotonic() + settings.polymarket_cooldown_seconds
            logger.warning(
                "Polymarket unreachable; pausing requests for %ss",
                settings.polymarket_cooldown_seconds,
            )

    def reset(self) -> None:
        self._failures = 0
        self._open_until = 0.0


breaker = _CircuitBreaker()


def _parse_json_field(value: object) -> object:
    """Gamma encodes list fields as JSON strings; decode them tolerantly."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _extract_yes(market: dict) -> tuple[str | None, float | None]:
    """Return the YES token id and its price, read as a probability."""
    outcomes = _parse_json_field(market.get("outcomes", []))
    prices = _parse_json_field(market.get("outcomePrices", []))
    token_ids = _parse_json_field(market.get("clobTokenIds", []))

    if not isinstance(outcomes, list) or not isinstance(token_ids, list):
        return None, None

    for index, outcome in enumerate(outcomes):
        if str(outcome).strip().lower() != "yes":
            continue
        if index >= len(token_ids):
            return None, None

        probability = None
        if isinstance(prices, list) and index < len(prices):
            probability = _to_float(prices[index], default=None)  # type: ignore[arg-type]

        return str(token_ids[index]), probability

    return None, None


def _direction(question: str) -> str | None:
    if DOWNSIDE_PATTERN.search(question):
        return "downside"
    if UPSIDE_PATTERN.search(question):
        return "upside"
    return None


async def search_events(query: str) -> list[dict]:
    """Search active Polymarket events."""
    settings = get_settings()

    if breaker.is_open:
        raise UpstreamError(PROVIDER, "provider unreachable (circuit open)")

    url = f"{settings.polymarket_gamma_url}/public-search"

    try:
        response = await get_client().get(
            url,
            params={"q": query, "limit_per_type": 20, "events_status": "active"},
            timeout=settings.polymarket_timeout_seconds,
        )
    except Exception as error:  # network failures must not break analysis
        breaker.record_failure()
        raise UpstreamError(PROVIDER, f"public-search unreachable: {error}") from error

    if response.status_code != 200:
        breaker.record_failure()
        raise UpstreamError(
            PROVIDER,
            f"public-search returned {response.status_code}",
            response.status_code,
        )

    breaker.record_success()
    return response.json().get("events") or []


# A 300-second window at minute fidelity was the original setting, carried over
# from reference.ipynb. It returned exactly +0.00% on nearly every market: a
# book holding a few hundred dollars simply does not trade within any given
# minute, so first and last price were the same tick. A day at hourly fidelity
# actually moves, and is still short enough to read as "what changed recently".
PROBABILITY_WINDOW_SECONDS = 24 * 60 * 60
PROBABILITY_FIDELITY_MINUTES = 60

# Below this, a reported move is as likely to be one stale quote as real news.
MIN_LIQUIDITY_FOR_CHANGE = 1_000.0


async def fetch_probability_change(
    token_id: str, window_seconds: int = PROBABILITY_WINDOW_SECONDS
) -> float | None:
    """Relative change in a YES token's price over a trailing window."""
    settings = get_settings()

    if breaker.is_open:
        return None

    now = int(time.time())

    try:
        response = await get_client().get(
            f"{settings.polymarket_clob_url}/prices-history",
            params={
                "market": token_id,
                "startTs": now - window_seconds,
                "endTs": now,
                "fidelity": PROBABILITY_FIDELITY_MINUTES,
            },
            timeout=settings.polymarket_timeout_seconds,
        )
    except Exception as error:
        logger.debug("prices-history unreachable for %s: %s", token_id, error)
        return None

    if response.status_code != 200:
        return None

    history = response.json().get("history") or []
    if len(history) < 2:
        return None

    first = _to_float(history[0].get("p"))
    last = _to_float(history[-1].get("p"))
    if first == 0:
        return None

    return (last - first) / first


async def get_asset_markets(asset: str, with_change: bool = False) -> list[PredictionMarket]:
    """Find the most liquid active markets relevant to one asset."""
    entry = ASSET_QUERIES.get(asset.upper())
    if entry is None:
        return []

    queries, relevance = entry
    markets: list[PredictionMarket] = []
    seen: set[str] = set()

    for query in queries:
        try:
            events = await search_events(query)
        except UpstreamError as error:
            logger.warning("Polymarket search failed for %s: %s", query, error)
            continue

        for event in events:
            event_title = event.get("title") or ""
            event_text = f"{event_title} {event.get('description') or ''}"

            for market in event.get("markets") or []:
                if market.get("closed"):
                    continue

                question = market.get("question") or ""
                if not relevance.search(f"{question} {event_text}"):
                    continue

                market_id = str(market.get("id"))
                if market_id in seen:
                    continue
                seen.add(market_id)

                token_id, probability = _extract_yes(market)
                if token_id is None or probability is None:
                    continue

                end_date = market.get("endDate") or event.get("endDate") or None

                markets.append(
                    PredictionMarket(
                        question=question,
                        event=event_title,
                        probability=probability,
                        yes_token_id=token_id,
                        liquidity=_to_float(market.get("liquidity")),
                        volume=_to_float(market.get("volume")),
                        direction=_direction(question),
                        threshold=implied.parse_threshold(question),
                        end_date=str(end_date)[:10] if end_date else None,
                    )
                )

    # Deepest markets first — they carry the most information.
    markets.sort(key=lambda m: (m.liquidity, m.volume), reverse=True)
    markets = markets[:MAX_MARKETS_PER_ASSET]

    if with_change and markets:
        # Thin books report a flat line whatever the window, so they are not
        # asked: a None reads as "no signal", which is the truth, while a 0.0
        # would read as "no movement", which is a claim the data cannot support.
        deep = [m for m in markets if m.liquidity >= MIN_LIQUIDITY_FOR_CHANGE]
        changes = await asyncio.gather(
            *(fetch_probability_change(m.yes_token_id) for m in deep)  # type: ignore[arg-type]
        )
        for market, change in zip(deep, changes, strict=True):
            market.probability_change_24h = change

    return markets


async def get_markets_for_assets(
    assets: list[str], with_change: bool = False
) -> list[AssetPredictionMarkets]:
    """Fetch prediction markets for several assets concurrently."""
    supported = [asset for asset in assets if asset.upper() in ASSET_QUERIES]
    if not supported:
        return []

    results = await asyncio.gather(
        *(get_asset_markets(asset, with_change) for asset in supported),
        return_exceptions=True,
    )

    output: list[AssetPredictionMarkets] = []
    for asset, result in zip(supported, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("Prediction markets unavailable for %s: %s", asset, result)
            continue
        output.append(AssetPredictionMarkets(asset=asset, markets=result))

    return output


def compute_market_stress(
    asset_markets: list[AssetPredictionMarkets],
    max_multiplier: float = 1.5,
) -> MarketStress:
    """Condense downside prediction markets into a volatility multiplier.

    The score is the liquidity-weighted mean probability assigned to downside
    questions. Deep markets pricing a fall as likely raise simulated
    volatility; thin or quiet markets barely move it.

    This is an intentionally simple stand-in. Reading prediction markets
    properly — distinguishing a 10% chance of a 5% dip from a 10% chance of a
    50% crash — belongs to the market analysis agent, which is out of scope
    here. Keeping the mapping bounded and explicit means the simulation can
    never be quietly dominated by this signal.
    """
    weighted_sum = 0.0
    total_liquidity = 0.0
    considered = 0

    for entry in asset_markets:
        for market in entry.markets:
            if market.direction != "downside" or market.probability is None:
                continue
            # Liquidity is the weight, floored so that a thin market still
            # counts for something.
            weight = max(market.liquidity, 1.0)
            weighted_sum += market.probability * weight
            total_liquidity += weight
            considered += 1

    if considered == 0 or total_liquidity == 0:
        # "Available" means markets were actually retrieved, not merely that
        # assets were looked up. An unreachable provider must not masquerade
        # as a calm market.
        any_markets = any(entry.markets for entry in asset_markets)
        return MarketStress(
            score=0.0,
            volatility_multiplier=1.0,
            markets_considered=0,
            total_liquidity=0.0,
            available=any_markets,
        )

    score = min(max(weighted_sum / total_liquidity, 0.0), 1.0)

    return MarketStress(
        score=score,
        volatility_multiplier=1.0 + score * (max_multiplier - 1.0),
        markets_considered=considered,
        total_liquidity=total_liquidity,
        available=True,
    )
