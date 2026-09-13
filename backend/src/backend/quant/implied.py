"""Market-implied distributions from prediction markets.

A binary market on a price level is a probability statement about that level.
``Will ETH dip to $1,000 by December 31, 2026?`` trading at 6.5c says the
market puts 6.5% on ``price <= 1000`` at that date. ``Will ETH reach $8,000``
at 2.15c says 2.15% on ``price >= 8000``, so ``1 - p`` is a point on the same
curve.

A family of these on one asset at one expiry is therefore a **market-implied
cumulative distribution** — not a sentiment score, a distribution, priced by
people with money at risk.

``compute_market_stress`` throws this information away: it averages every
downside probability into one bounded volatility multiplier, so a 2% chance of
a catastrophic fall and a 14% chance of a mild one are the same input. This
module keeps the levels, and turns them into a volatility the simulator can
actually use.

**What is fitted.** One lognormal per asset per expiry, consistent with
``monte_carlo``'s zero-drift convention: under ``DriftMode.ZERO`` the expected
simple return is zero, so the log drift is ``-sigma^2 / 2`` and

    P(S_T <= K) = Phi( ( ln(K / S_0) + sigma^2 T / 2 ) / ( sigma sqrt(T) ) )

The one free parameter, ``sigma``, is chosen to reproduce the observed
probabilities as closely as possible, weighted by liquidity.

**What this does and does not buy.** It replaces a volatility measured from the
past with one the market is pricing for the future — the single largest
improvement available to the tail estimates, and the fix for the "volatility is
historical" limitation. It does **not** make the model fat-tailed: a lognormal
fitted to market quantiles is still a lognormal, and real crypto returns are
more extreme. It is also risk-neutral, not real-world: prediction-market prices
carry risk premia and fees. Both caveats are deliberate — a better-centred
lognormal is an honest improvement, and pretending otherwise is not.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from backend.models.market import AssetPredictionMarkets, PredictionMarket

# Below this many points at one expiry there is nothing to fit: two points and
# one free parameter is interpolation, not estimation.
MIN_POINTS = 3

# A fitted volatility outside this range is not a market view, it is a parsing
# or data error. 5% annualised is calmer than any crypto asset has ever been;
# 400% is beyond even a collapsing token.
MIN_SIGMA = 0.05
MAX_SIGMA = 4.0

# Probabilities this close to 0 or 1 carry almost no information about sigma
# and are the most likely to be stale on a thin book.
EXTREME_PROBABILITY = 0.005

# A curve that has to be repaired more than this is not trustworthy.
MAX_VIOLATION_RATIO = 0.25

TRADING_DAYS = 365.0

# ``$1,500``, ``$0.05``, ``$150k``, ``$1.2M``. The suffix multiplies.
#
# The lookahead is load-bearing: without it ``$1,000 by December 31`` reads the
# ``b`` of ``by`` as a billions suffix and returns one trillion. A suffix must
# be a single letter that does not continue into a word.
_AMOUNT = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s?([kKmMbB])?(?![A-Za-z0-9.])")
_MULTIPLIER = {"k": 1e3, "m": 1e6, "b": 1e9, "": 1.0}


@dataclass(frozen=True)
class ImpliedPoint:
    """One market, read as ``P(price <= threshold)`` at a single expiry."""

    threshold: float
    probability_at_or_below: float
    direction: str
    liquidity: float = 0.0
    question: str = ""
    repaired: bool = False
    source: str = "polymarket"


@dataclass(frozen=True)
class ImpliedFit:
    """A lognormal fitted to one asset's implied CDF at one expiry."""

    symbol: str
    expiry: str
    years: float
    spot: float
    sigma: float
    rmse: float
    points_used: int
    violations_repaired: int
    points: list[ImpliedPoint] = field(default_factory=list)
    horizon_matched: bool = True

    @property
    def sources(self) -> tuple[str, ...]:
        """Which exchanges contributed, so an explanation can cite them."""
        return tuple(sorted({point.source for point in self.points}))

    @property
    def quality(self) -> str:
        """How well the lognormal reproduces the quotes it was fitted to.

        This measures the fit and nothing else. Whether the expiry suits the
        simulation horizon is a separate question, handled by
        ``horizon_matched`` and applied in ``weight_for`` — conflating the two
        makes a good fit at the wrong expiry indistinguishable from a bad fit
        at the right one, and they call for different responses.
        """
        if self.rmse <= 0.02 and self.points_used >= 5:
            return "good"
        if self.rmse <= 0.05:
            return "fair"
        return "poor"


def parse_threshold(question: str) -> float | None:
    """The dollar level a market resolves on, or None.

    Returns None for questions carrying no level (``Ethereum all time high by
    September 30, 2026?``) and for range markets naming two levels, which are
    a different statement and must not be read as one side of a CDF.
    """
    matches = _AMOUNT.findall(question or "")
    if len(matches) != 1:
        return None

    digits, suffix = matches[0]
    try:
        amount = float(digits.replace(",", ""))
    except ValueError:
        return None

    value = amount * _MULTIPLIER[suffix.lower() if suffix else ""]
    return value if value > 0 else None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _years_to(expiry: str, today: date | None = None) -> float | None:
    """Fraction of a year until an ISO date, or None if it is past or unparsable."""
    try:
        end = datetime.fromisoformat(expiry.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        try:
            end = date.fromisoformat(expiry[:10])
        except (ValueError, TypeError, IndexError):
            return None

    reference = today or datetime.now(UTC).date()
    days = (end - reference).days
    return days / TRADING_DAYS if days >= 1 else None


def points_from_markets(markets: list[PredictionMarket]) -> dict[str, list[ImpliedPoint]]:
    """Group an asset's markets into implied CDF points, keyed by expiry.

    Expiry is the grouping key and not an optional refinement: ``31 Dec 2026``
    and ``30 Sep 2026`` are different random variables. Mixing them produces a
    curve that looks plausible and means nothing.
    """
    grouped: dict[str, list[ImpliedPoint]] = {}

    for market in markets:
        if market.probability is None or market.direction is None:
            continue
        if not market.end_date:
            continue

        threshold = market.threshold
        if threshold is None:
            threshold = parse_threshold(market.question)
        if threshold is None:
            continue

        probability = float(market.probability)
        if not 0.0 <= probability <= 1.0:
            continue

        if market.direction == "downside":
            p_le = probability
        elif market.direction == "upside":
            p_le = 1.0 - probability
        else:
            continue

        if min(p_le, 1.0 - p_le) < EXTREME_PROBABILITY:
            continue

        expiry = market.end_date[:10]
        grouped.setdefault(expiry, []).append(
            ImpliedPoint(
                threshold=threshold,
                probability_at_or_below=p_le,
                direction=market.direction,
                liquidity=market.liquidity,
                question=market.question,
                source=getattr(market, "source", "polymarket"),
            )
        )

    for expiry in grouped:
        grouped[expiry] = _deduplicate(grouped[expiry])

    return grouped


def _deduplicate(points: list[ImpliedPoint]) -> list[ImpliedPoint]:
    """One point per threshold, keeping the deepest market, sorted by level."""
    best: dict[float, ImpliedPoint] = {}
    for point in points:
        existing = best.get(point.threshold)
        if existing is None or point.liquidity > existing.liquidity:
            best[point.threshold] = point
    return sorted(best.values(), key=lambda p: p.threshold)


def enforce_monotonic(points: list[ImpliedPoint]) -> tuple[list[ImpliedPoint], int]:
    """Repair a CDF that decreases, and report how much repair was needed.

    A cumulative distribution cannot fall as the threshold rises. When it
    appears to, the cause is almost always a stale quote on a thin book rather
    than a real disagreement, so the running maximum is taken — the standard
    isotonic repair for this shape. The count is returned because a curve
    needing many repairs should not be trusted, and that is the caller's
    decision to make.
    """
    repaired: list[ImpliedPoint] = []
    ceiling = 0.0
    violations = 0

    for point in points:
        if point.probability_at_or_below < ceiling - 1e-9:
            violations += 1
            repaired.append(
                ImpliedPoint(
                    threshold=point.threshold,
                    probability_at_or_below=ceiling,
                    direction=point.direction,
                    liquidity=point.liquidity,
                    question=point.question,
                    source=point.source,
                    repaired=True,
                )
            )
        else:
            ceiling = point.probability_at_or_below
            repaired.append(point)

    return repaired, violations


def _model_probability(threshold: float, spot: float, sigma: float, years: float) -> float:
    """``P(S_T <= threshold)`` under the zero-simple-drift lognormal."""
    if spot <= 0 or sigma <= 0 or years <= 0:
        return 0.0
    scale = sigma * math.sqrt(years)
    d = (math.log(threshold / spot) + 0.5 * sigma * sigma * years) / scale
    return _norm_cdf(d)


def _weighted_error(points: list[ImpliedPoint], spot: float, sigma: float, years: float) -> float:
    """Liquidity-weighted RMSE between the model and the market, in probability."""
    total_weight = 0.0
    total = 0.0
    for point in points:
        weight = max(point.liquidity, 1.0)
        error = _model_probability(point.threshold, spot, sigma, years) - point.probability_at_or_below
        total += weight * error * error
        total_weight += weight
    return math.sqrt(total / total_weight) if total_weight else float("inf")


def fit_sigma(points: list[ImpliedPoint], spot: float, years: float) -> tuple[float, float]:
    """Annualised volatility best reproducing the observed probabilities.

    One free parameter, so a coarse log-spaced sweep followed by a golden-section
    refinement is both sufficient and dependency-free — the objective is smooth
    and practically unimodal in sigma, and this avoids a SciPy dependency for a
    one-dimensional search.
    """
    grid = [MIN_SIGMA * (MAX_SIGMA / MIN_SIGMA) ** (i / 96) for i in range(97)]
    errors = [_weighted_error(points, spot, sigma, years) for sigma in grid]
    index = min(range(len(grid)), key=errors.__getitem__)

    low = grid[max(index - 1, 0)]
    high = grid[min(index + 1, len(grid) - 1)]

    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = low, high
    c = b - invphi * (b - a)
    d = a + invphi * (b - a)
    fc = _weighted_error(points, spot, c, years)
    fd = _weighted_error(points, spot, d, years)

    for _ in range(60):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - invphi * (b - a)
            fc = _weighted_error(points, spot, c, years)
        else:
            a, c, fc = c, d, fd
            d = a + invphi * (b - a)
            fd = _weighted_error(points, spot, d, years)
        if abs(b - a) < 1e-6:
            break

    sigma = (a + b) / 2.0
    return sigma, _weighted_error(points, spot, sigma, years)


# An expiry within this factor of the simulation horizon is treated as
# matching it. Half to double the horizon is close enough that the flat
# term-structure assumption is not doing much work.
HORIZON_TOLERANCE = 2.0


def fit_asset(
    symbol: str,
    markets: list[PredictionMarket],
    spot: float,
    today: date | None = None,
    horizon_days: int | None = None,
) -> ImpliedFit | None:
    """Best implied fit for one asset, or None when the markets cannot support one.

    Selection is horizon-first, then depth.

    A fitted sigma is annualised by construction — it comes out of the same
    ``sigma sqrt(T)`` the simulator uses — so a five-day ladder does produce a
    usable annual figure. That is the whole reason a short-dated Kalshi ladder
    is worth reading at all, and it is what makes this work on day one, before
    any long-dated series is wired in.

    But annualising is not free. It assumes the term structure is flat, and
    crypto's is not: short-dated implied volatility spikes around events and
    mean-reverts. So when an expiry near the simulation horizon exists, it wins
    even if a shorter one is deeper, and a fit taken from a mismatched expiry
    is marked ``horizon_matched=False`` and has its quality reduced — which in
    turn lowers how far the blend moves toward it.

    Within either group, the deepest ladder wins: liquidity is what makes a
    probability worth reading.
    """
    if spot <= 0:
        return None

    target_years = (horizon_days / TRADING_DAYS) if horizon_days else None
    candidates: list[ImpliedFit] = []

    for expiry, raw in points_from_markets(markets).items():
        years = _years_to(expiry, today)
        if years is None:
            continue

        points, violations = enforce_monotonic(raw)
        if len(points) < MIN_POINTS:
            continue
        if violations / max(len(points) - 1, 1) > MAX_VIOLATION_RATIO:
            continue

        sigma, rmse = fit_sigma(points, spot, years)
        if not MIN_SIGMA * 1.01 < sigma < MAX_SIGMA * 0.99:
            # Pinned to a bound: the fit did not converge inside a believable
            # range, so the inputs are wrong rather than the market extreme.
            continue

        if target_years is None:
            matched = True
        else:
            ratio = years / target_years
            matched = 1 / HORIZON_TOLERANCE <= ratio <= HORIZON_TOLERANCE

        candidates.append(
            ImpliedFit(
                symbol=symbol,
                expiry=expiry,
                years=years,
                spot=spot,
                sigma=sigma,
                rmse=rmse,
                points_used=len(points),
                violations_repaired=violations,
                points=points,
                horizon_matched=matched,
            )
        )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda fit: (fit.horizon_matched, sum(p.liquidity for p in fit.points)),
    )


def merge_sources(
    *sources: list[AssetPredictionMarkets],
) -> list[AssetPredictionMarkets]:
    """Combine several exchanges' markets per asset.

    Blending happens here, at the level of individual quotes, rather than by
    averaging two finished signals. Every market is a point on the same curve
    whatever exchange priced it, so one fit over the union is both simpler and
    strictly better informed than reconciling two fits afterwards. Each point
    keeps its ``source``, so the fit can still say who contributed.

    An exchange that is unreachable contributes nothing and changes nothing —
    the remaining points are still a distribution.
    """
    combined: dict[str, list[PredictionMarket]] = {}
    for group in sources:
        for entry in group:
            combined.setdefault(entry.asset.upper(), []).extend(entry.markets)

    return [
        AssetPredictionMarkets(asset=asset, markets=markets)
        for asset, markets in sorted(combined.items())
        if markets
    ]


def fit_assets(
    asset_markets: list[AssetPredictionMarkets],
    spots: dict[str, float],
    today: date | None = None,
    horizon_days: int | None = None,
) -> dict[str, ImpliedFit]:
    """Implied fits for every asset that supports one, keyed by symbol."""
    fits: dict[str, ImpliedFit] = {}
    for entry in asset_markets:
        spot = spots.get(entry.asset.upper())
        if spot is None:
            continue
        fit = fit_asset(entry.asset.upper(), entry.markets, spot, today, horizon_days)
        if fit is not None:
            fits[entry.asset.upper()] = fit
    return fits


def blend(historical: float, implied: float, weight: float = 0.5) -> float:
    """Blend a realised volatility with an implied one.

    Neither is the truth. The realised estimate is a real measurement of the
    wrong period; the implied one is the right period seen through risk premia
    and a thin book. Averaging them is a deliberately conservative default —
    ``weight`` moves toward the implied value as confidence in the fit grows.
    """
    weight = min(max(weight, 0.0), 1.0)
    return (1.0 - weight) * historical + weight * implied


# A fit read at an expiry far from the simulation horizon still carries real
# information — it is a market price, not a guess — but annualising it assumes
# a flat term structure that crypto does not have. Halving its influence keeps
# the fallback useful without letting a five-day ladder dictate a ninety-day
# view.
HORIZON_MISMATCH_PENALTY = 0.5

QUALITY_WEIGHT = {"good": 0.7, "fair": 0.5, "poor": 0.0}


def weight_for(fit: ImpliedFit) -> float:
    """How far to move toward the implied volatility.

    Two independent discounts: how well the curve was fitted, and whether its
    expiry suits the horizon being simulated. A poor fit is worth nothing at
    any horizon, so the penalty cannot resurrect one.
    """
    weight = QUALITY_WEIGHT[fit.quality]
    if not fit.horizon_matched:
        weight *= HORIZON_MISMATCH_PENALTY
    return weight
