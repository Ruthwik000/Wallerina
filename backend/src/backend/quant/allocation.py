"""Deterministic allocation engine.

Specification section 2 is the constraint that shapes this module: the LLM must
never invent portfolio percentages. This file decides the number; the judgement
agent only explains it.

Every adjustment is a named, bounded contribution recorded on the result, so
the decision is auditable and the explainer never has to re-derive it.

The engine answers one question:

    Given the user's goal, the current book, and the measured risk environment,
    how much stablecoin exposure is appropriate?
"""

from __future__ import annotations

import numpy as np

from backend.models.goal import (
    AllocationDecision,
    AllocationDriver,
    PortfolioRules,
)

# Reference points for the risk environment. A portfolio at REFERENCE_VOLATILITY
# with no concentration or correlation problems sits at the goal's base ratio.
REFERENCE_VOLATILITY = 0.55
VOLATILITY_SENSITIVITY = 0.45
MAX_VOLATILITY_SHIFT = 0.22

CONCENTRATION_THRESHOLD = 0.35
CONCENTRATION_SENSITIVITY = 0.30
MAX_CONCENTRATION_SHIFT = 0.12

CORRELATION_THRESHOLD = 0.55
CORRELATION_SENSITIVITY = 0.28
MAX_CORRELATION_SHIFT = 0.12

MAX_STRESS_SHIFT = 0.10

# Half-width of the acceptable band around the target.
BAND_HALF_WIDTH = 0.05


def _clamp(value: float, low: float, high: float) -> float:
    return float(min(max(value, low), high))


def mean_pairwise_correlation(
    correlation: np.ndarray, stable_mask: np.ndarray | None = None
) -> float:
    """Average off-diagonal correlation of the volatile sleeve.

    Stablecoins are excluded: their near-zero correlation with everything would
    drag the average down and disguise a volatile book that moves as one.
    """
    if correlation.size == 0 or correlation.shape[0] < 2:
        return 0.0

    matrix = np.asarray(correlation, dtype=float)

    if stable_mask is not None and stable_mask.size == matrix.shape[0]:
        keep = ~np.asarray(stable_mask, dtype=bool)
        if keep.sum() < 2:
            return 0.0
        matrix = matrix[np.ix_(keep, keep)]

    n = matrix.shape[0]
    off_diagonal = matrix[~np.eye(n, dtype=bool)]

    return float(np.mean(off_diagonal)) if off_diagonal.size else 0.0


def decide(
    *,
    rules: PortfolioRules,
    current_stablecoin_ratio: float,
    annual_volatility: float,
    concentration: float,
    correlation: float,
    market_stress: float | None,
    observations: int,
    drawdown_probe=None,
) -> AllocationDecision:
    """Compute the target stablecoin ratio.

    ``drawdown_probe`` is an optional callable taking a candidate stablecoin
    ratio and returning the simulated drawdown at that allocation. When
    supplied, the maximum-drawdown rule is enforced as a hard constraint by
    searching for the lowest ratio that satisfies it.
    """
    drivers: list[AllocationDriver] = []
    ratio = rules.base_stablecoin_ratio

    drivers.append(
        AllocationDriver(
            name="Goal baseline",
            contribution=ratio,
            detail=(
                f"{rules.risk_tolerance} risk tolerance sets a base stablecoin "
                f"allocation of {ratio:.0%}"
            ),
        )
    )

    # --- Volatility -------------------------------------------------------
    # The dominant signal: a book whose realised volatility sits above the
    # reference band needs more ballast to hold the same risk.
    volatility_gap = annual_volatility - REFERENCE_VOLATILITY
    volatility_shift = _clamp(
        volatility_gap * VOLATILITY_SENSITIVITY,
        -MAX_VOLATILITY_SHIFT,
        MAX_VOLATILITY_SHIFT,
    )
    if abs(volatility_shift) > 0.001:
        ratio += volatility_shift
        drivers.append(
            AllocationDriver(
                name="Realised volatility",
                contribution=volatility_shift,
                detail=(
                    f"Annualised volatility of {annual_volatility:.0%} is "
                    f"{abs(volatility_gap):.0%} "
                    f"{'above' if volatility_gap > 0 else 'below'} the "
                    f"{REFERENCE_VOLATILITY:.0%} reference"
                ),
            )
        )

    # --- Concentration ----------------------------------------------------
    concentration_excess = max(concentration - CONCENTRATION_THRESHOLD, 0.0)
    concentration_shift = _clamp(
        concentration_excess * CONCENTRATION_SENSITIVITY, 0.0, MAX_CONCENTRATION_SHIFT
    )
    if concentration_shift > 0.001:
        ratio += concentration_shift
        drivers.append(
            AllocationDriver(
                name="Concentration",
                contribution=concentration_shift,
                detail=(
                    f"Herfindahl index of {concentration:.2f} exceeds the "
                    f"{CONCENTRATION_THRESHOLD:.2f} threshold; the book is "
                    "carried by a small number of positions"
                ),
            )
        )

    # --- Correlation ------------------------------------------------------
    # Position count overstates diversification when the volatile sleeve moves
    # together, so high correlation is treated as concentration by another name.
    correlation_excess = max(correlation - CORRELATION_THRESHOLD, 0.0)
    correlation_shift = _clamp(
        correlation_excess * CORRELATION_SENSITIVITY, 0.0, MAX_CORRELATION_SHIFT
    )
    if correlation_shift > 0.001:
        ratio += correlation_shift
        drivers.append(
            AllocationDriver(
                name="Correlation clustering",
                contribution=correlation_shift,
                detail=(
                    f"Mean pairwise correlation across the volatile sleeve is "
                    f"{correlation:.2f}; those positions are behaving as one "
                    "exposure"
                ),
            )
        )

    # --- Market stress ----------------------------------------------------
    if market_stress is not None and market_stress > 0:
        stress_shift = _clamp(market_stress * MAX_STRESS_SHIFT, 0.0, MAX_STRESS_SHIFT)
        if stress_shift > 0.001:
            ratio += stress_shift
            drivers.append(
                AllocationDriver(
                    name="Prediction markets",
                    contribution=stress_shift,
                    detail=(
                        f"Liquidity-weighted downside probability of "
                        f"{market_stress:.0%} across active markets"
                    ),
                )
            )

    signal_ratio = _clamp(ratio, 0.0, 1.0)

    # --- Hard constraints -------------------------------------------------
    binding: str | None = None
    drawdown_at_target: float | None = None

    # The drawdown limit is a rule, not a signal: it can raise the target above
    # what the signals alone asked for, and it is checked before the band.
    if drawdown_probe is not None:
        required, drawdown_at_target = _minimum_ratio_for_drawdown(
            drawdown_probe, rules.maximum_drawdown, signal_ratio
        )
        if required > signal_ratio + 0.005:
            drivers.append(
                AllocationDriver(
                    name="Maximum drawdown rule",
                    contribution=required - signal_ratio,
                    detail=(
                        f"Simulated drawdown stays within the "
                        f"{rules.maximum_drawdown:.0%} limit only from "
                        f"{required:.0%} stablecoins"
                    ),
                )
            )
            signal_ratio = required
            binding = "maximum_drawdown"

    target = _clamp(
        signal_ratio, rules.minimum_stablecoin_ratio, rules.maximum_stablecoin_ratio
    )

    if target > signal_ratio + 1e-9:
        binding = "minimum_stablecoin_ratio"
    elif target < signal_ratio - 1e-9:
        binding = "maximum_stablecoin_ratio"
        drivers.append(
            AllocationDriver(
                name="Risk ceiling",
                contribution=target - signal_ratio,
                detail=(
                    f"Signals asked for {signal_ratio:.0%}, capped at the goal's "
                    f"{rules.maximum_stablecoin_ratio:.0%} maximum"
                ),
            )
        )

    band = (
        _clamp(target - BAND_HALF_WIDTH, rules.minimum_stablecoin_ratio, 1.0),
        _clamp(target + BAND_HALF_WIDTH, 0.0, rules.maximum_stablecoin_ratio),
    )

    drift = target - current_stablecoin_ratio
    inside_band = band[0] <= current_stablecoin_ratio <= band[1]
    rebalance = (not inside_band) and abs(drift) > rules.rebalance_threshold

    return AllocationDecision(
        target_stablecoin_ratio=target,
        acceptable_range=band,
        current_stablecoin_ratio=current_stablecoin_ratio,
        confidence=_confidence(observations, market_stress, correlation),
        rebalance_required=rebalance,
        drift=drift,
        drivers=drivers,
        binding_constraint=binding,
        drawdown_at_target=drawdown_at_target,
        rules=rules,
    )


def _minimum_ratio_for_drawdown(
    probe, limit: float, floor: float
) -> tuple[float, float]:
    """Lowest stablecoin ratio whose simulated drawdown meets the limit.

    Drawdown falls monotonically as stablecoin weight rises, so a bisection is
    both valid and much cheaper than sweeping every candidate: a simulation run
    costs real time, and this converges in a handful of probes.
    """
    at_floor = probe(floor)
    if at_floor <= limit:
        return floor, at_floor

    low, high = floor, 1.0
    at_high = probe(high)
    if at_high > limit:
        # Even a fully stable book breaches the limit (a depegging stablecoin,
        # say). Nothing more can be done with allocation alone.
        return high, at_high

    best = high
    best_drawdown = at_high

    for _ in range(6):
        mid = (low + high) / 2
        value = probe(mid)
        if value <= limit:
            best, best_drawdown = mid, value
            high = mid
        else:
            low = mid

    return best, best_drawdown


def _confidence(
    observations: int, market_stress: float | None, correlation: float
) -> float:
    """How much the engine trusts this decision.

    Driven by the evidence available, not by how strong the recommendation is:
    a short price history or missing prediction-market data lowers confidence
    even when the signals agree.
    """
    # 180 days of history is treated as a full sample.
    history = _clamp(observations / 180, 0.0, 1.0)

    confidence = 0.55 + 0.30 * history

    if market_stress is None:
        confidence -= 0.08  # no external corroboration

    # A tightly correlated book is easier to reason about than a scattered one.
    if correlation > CORRELATION_THRESHOLD:
        confidence += 0.05

    return round(_clamp(confidence, 0.0, 0.99), 2)
