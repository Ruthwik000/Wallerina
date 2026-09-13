"""Kalshi client: price-ladder markets read as a cumulative distribution.

Kalshi is a CFTC-regulated exchange. Its crypto price markets are published as
a **strike ladder** — one binary market per level, all resolving on the same
date — which is a far richer object than the scattered thresholds Polymarket
offers. A single live BTC event carries roughly 46 strikes from $64,500 to
$89,000 in $500 steps, each with a two-sided quote.

Every detail below was verified against the live API rather than taken from the
documentation, and three of them contradict what the published guides say.

**Base URL.** ``https://external-api.kalshi.com/trade-api/v2``. Not
``trading-api.kalshi.com``, not ``api.elections.kalshi.com``. Market data needs
no authentication.

**Prices are decimal strings, not integer cents.** The live fields are
``yes_bid_dollars: "0.9400"`` and ``yes_ask_dollars: "0.9500"``; size and
volume fields carry an ``_fp`` suffix. Most guides and older SDKs describe
integer cents (1-99), and coding to that would make every probability a
hundredth of its true value — silently, since nothing would raise.

**Status is "active", not "open".** ``/markets?status=open`` returns an empty
array.

**Series lookups go through events.** ``/markets?series_ticker=X`` returns
nothing once that series' events have expired, so the path is
``/events?series_ticker=X&status=open`` and then ``/markets?event_ticker=...``.

Markets are returned as ``PredictionMarket``, the same model the Polymarket
client produces, so ``quant/implied.py`` consumes both without knowing which
exchange a point came from and the two blend by concatenation.

Read-only market data only. The order and portfolio endpoints exist and are
never called: Wallerina gives advice and never trades.
"""

from __future__ import annotations

import asyncio
import logging
import time

from backend.core.config import get_settings
from backend.models.market import AssetPredictionMarkets, PredictionMarket
from backend.services.http import UpstreamError, get_client

logger = logging.getLogger(__name__)

PROVIDER = "kalshi"

# Curated series per asset. A category scan is not a substitute: /series
# returns 115 crypto series that are mostly FDV bets, airdrop odds, token
# launches and 15-minute scalps, the list is paginated, and KXBTCD — the most
# useful series found — was not on the first page. Verify tickers against the
# live API before adding to this map.
ASSET_SERIES: dict[str, tuple[str, ...]] = {
    "BTC": ("KXBTCD", "KXBTCQ", "KXBTCYEAR"),
    "WBTC": ("KXBTCD", "KXBTCQ", "KXBTCYEAR"),
    "ETH": ("KXETHD", "KXETHMAXMON"),
    "WETH": ("KXETHD", "KXETHMAXMON"),
    "SOL": ("KXSOLD", "KXSOLD26"),
    "DOGE": ("KXDOGE",),
    "XRP": ("KXRIPPLED", "KXXRPY"),
    "LINK": ("KXLINKD", "KXLINK"),
    "BNB": ("KXBNBD", "KXBNB"),
    "LTC": ("KXLTCD",),
    "BCH": ("KXBCHD",),
    "NEAR": ("KXNEARD", "KXNEAR"),
    "AVAX": ("KXAVAXMINY",),
}

# Not a price ladder, but the market that prices the risk the stablecoin
# analyst exists to assess. Kept separate because it answers a different
# question and must never be fed into a price distribution.
STABLECOIN_SERIES: dict[str, str] = {"USDT": "KXUSDTMIN"}

MAX_EVENTS_PER_SERIES = 4
MAX_STRIKES_PER_EVENT = 80


class _CircuitBreaker:
    """Stop hammering an exchange that is not answering.

    Mirrors the Polymarket breaker deliberately. A second upstream with no
    breaker would simply become the new way for one slow provider to add its
    full timeout to every analysis.
    """

    def __init__(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        if self._open_until and time.monotonic() < self._open_until:
            return True
        if self._open_until:
            self._open_until = 0.0
            self._failures = 0
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        settings = get_settings()
        self._failures += 1
        if self._failures >= settings.kalshi_failure_threshold:
            self._open_until = time.monotonic() + settings.kalshi_cooldown_seconds
            logger.warning(
                "Kalshi unreachable; pausing requests for %ss",
                settings.kalshi_cooldown_seconds,
            )

    def reset(self) -> None:
        self._failures = 0
        self._open_until = 0.0


breaker = _CircuitBreaker()


def _to_float(value: object, default: float = 0.0) -> float:
    """Parse Kalshi's decimal strings.

    Every numeric field arrives as a string: prices in dollars, sizes with an
    ``_fp`` suffix. The default matters — a missing price must not silently
    become a real one.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _get(path: str, params: dict) -> dict:
    settings = get_settings()

    if breaker.is_open:
        raise UpstreamError("Kalshi circuit breaker open")

    try:
        response = await get_client().get(
            f"{settings.kalshi_base_url}{path}",
            params=params,
            timeout=settings.kalshi_timeout_seconds,
        )
    except Exception as error:  # noqa: BLE001 - upstream failures are expected
        breaker.record_failure()
        raise UpstreamError(f"Kalshi request failed: {error}") from error

    if response.status_code != 200:
        breaker.record_failure()
        raise UpstreamError(f"Kalshi returned HTTP {response.status_code} for {path}")

    breaker.record_success()
    return response.json()


async def open_events(series_ticker: str) -> list[dict]:
    """Open events for a series, newest first.

    Going through events rather than straight to /markets is not a detour:
    ``/markets?series_ticker=X`` returns an empty array whenever that series'
    events have expired, which looks identical to a series that does not exist.
    """
    payload = await _get(
        "/events",
        {"series_ticker": series_ticker, "status": "open", "limit": MAX_EVENTS_PER_SERIES},
    )
    return payload.get("events") or []


async def event_markets(event_ticker: str) -> list[dict]:
    payload = await _get(
        "/markets", {"event_ticker": event_ticker, "limit": MAX_STRIKES_PER_EVENT}
    )
    return payload.get("markets") or []


def _mid_price(market: dict) -> float | None:
    """Mid of the two-sided quote, or None when it cannot be trusted.

    There is no dependable "last traded" price on a thin strike, but there is
    always a book. The spread is then a quality signal Polymarket never
    provided: a strike quoted 0.00/0.03 is the exchange shrugging, not a 1.5%
    probability.
    """
    settings = get_settings()

    bid = _to_float(market.get("yes_bid_dollars"), default=-1.0)
    ask = _to_float(market.get("yes_ask_dollars"), default=-1.0)

    if bid < 0 or ask < 0 or ask < bid:
        return None
    if ask - bid > settings.kalshi_max_spread:
        return None

    return (bid + ask) / 2.0


def _strike(market: dict) -> tuple[float, str] | None:
    """(level, direction) for a price-level market, or None.

    ``greater`` markets pay out above ``floor_strike``, so they read as upside;
    ``less`` markets pay out below ``cap_strike`` and read as downside. Both
    are points on one cumulative distribution. ``between`` markets name two
    levels and are a different statement, so they are skipped rather than
    guessed at.
    """
    strike_type = str(market.get("strike_type") or "").lower()

    if strike_type in ("greater", "greater_or_equal"):
        level = _to_float(market.get("floor_strike"), default=-1.0)
        return (level, "upside") if level > 0 else None

    if strike_type in ("less", "less_or_equal"):
        level = _to_float(market.get("cap_strike"), default=-1.0)
        return (level, "downside") if level > 0 else None

    return None


def to_prediction_market(market: dict) -> PredictionMarket | None:
    """One Kalshi strike as the model the implied-CDF fitter already reads."""
    settings = get_settings()

    if str(market.get("status") or "").lower() != "active":
        return None

    strike = _strike(market)
    if strike is None:
        return None
    level, direction = strike

    probability = _mid_price(market)
    if probability is None:
        return None

    open_interest = _to_float(market.get("open_interest_fp"))
    if open_interest < settings.kalshi_min_open_interest:
        return None

    expiration = str(market.get("expiration_time") or "")
    if not expiration:
        return None

    return PredictionMarket(
        question=market.get("title") or market.get("yes_sub_title") or market.get("ticker") or "",
        event=market.get("event_ticker"),
        probability=probability,
        yes_token_id=market.get("ticker"),
        # Open interest is the honest depth measure here: it is capital
        # currently at risk on this strike, where volume counts trades that
        # have already been closed out.
        liquidity=open_interest,
        volume=_to_float(market.get("volume_fp")),
        direction=direction,
        threshold=level,
        end_date=expiration[:10],
        source=PROVIDER,
    )


async def get_asset_markets(asset: str) -> list[PredictionMarket]:
    """Every usable strike across the curated series for one asset."""
    settings = get_settings()
    if not settings.kalshi_enabled:
        return []

    series = ASSET_SERIES.get(asset.upper())
    if not series:
        return []

    collected: list[PredictionMarket] = []

    for series_ticker in series:
        try:
            events = await open_events(series_ticker)
        except UpstreamError as error:
            logger.warning("Kalshi events unavailable for %s: %s", series_ticker, error)
            continue

        for event in events:
            ticker = event.get("event_ticker") or event.get("ticker")
            if not ticker:
                continue
            try:
                raw = await event_markets(str(ticker))
            except UpstreamError as error:
                logger.warning("Kalshi markets unavailable for %s: %s", ticker, error)
                continue

            for market in raw:
                parsed = to_prediction_market(market)
                if parsed is not None:
                    collected.append(parsed)

    collected.sort(key=lambda m: (m.liquidity, m.volume), reverse=True)
    return collected


async def get_markets_for_assets(assets: list[str]) -> list[AssetPredictionMarkets]:
    """Ladders for several assets concurrently, skipping the unsupported."""
    settings = get_settings()
    if not settings.kalshi_enabled:
        return []

    supported = [asset for asset in assets if asset.upper() in ASSET_SERIES]
    if not supported:
        return []

    results = await asyncio.gather(
        *(get_asset_markets(asset) for asset in supported), return_exceptions=True
    )

    output: list[AssetPredictionMarkets] = []
    for asset, result in zip(supported, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("Kalshi unavailable for %s: %s", asset, result)
            continue
        if result:
            output.append(AssetPredictionMarkets(asset=asset.upper(), markets=result))

    return output
