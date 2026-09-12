"""Monte Carlo simulation engine.

Simulates a portfolio forward under correlated geometric Brownian motion and
reports the distribution of outcomes. The engine is deliberately a *risk*
model, not a forecaster: see ``DriftMode`` below.

Design notes
------------

**Correlation.** Assets are driven by correlated normal shocks generated from
the Cholesky factor of the correlation matrix. This is what makes the result
meaningful for the allocation question the product asks — a book of five
volatile tokens that all move together is far riskier than its position count
suggests, and independent draws would hide exactly that.

**Drift.** By default the expected *simple* return of every asset is zero, so
the log drift is ``-σ²/2``. Estimating drift from a short price history mostly
measures noise and would turn the simulator into a naive trend extrapolator —
whatever rose recently would be projected to keep rising. The specification is
explicit that the system does not predict prices, so the honest default is a
driftless (martingale) market, with historical and shrunk modes available for
explicit what-if analysis.

**Memory.** Per-asset paths are generated in batches and immediately collapsed
into a portfolio value path, so only an ``(simulations, horizon + 1)`` array of
portfolio values is retained. A 50,000 x 365 run therefore costs roughly
150 MB rather than the multiple gigabytes a full per-asset cube would need.

**Variance reduction.** Antithetic sampling pairs every shock with its negative,
which reduces the standard error of the mean without biasing the distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from backend.quant.risk import TRADING_DAYS, nearest_positive_definite

# Simulations are generated in batches to bound peak memory.
BATCH_SIZE = 2_000


class DriftMode(StrEnum):
    ZERO = "zero"
    HISTORICAL = "historical"
    SHRUNK = "shrunk"


@dataclass(frozen=True)
class SimulationInputs:
    """Everything the engine needs about the assets being simulated.

    ``weights`` must sum to one and align with ``symbols``, ``volatilities``
    (annualised) and the rows/columns of ``correlation``.
    """

    symbols: list[str]
    weights: np.ndarray
    volatilities: np.ndarray
    correlation: np.ndarray
    initial_value: float
    historical_drift: np.ndarray | None = None

    def __post_init__(self) -> None:
        n = len(self.symbols)
        if self.weights.shape != (n,):
            raise ValueError(f"weights must have shape ({n},), got {self.weights.shape}")
        if self.volatilities.shape != (n,):
            raise ValueError(
                f"volatilities must have shape ({n},), got {self.volatilities.shape}"
            )
        if self.correlation.shape != (n, n):
            raise ValueError(
                f"correlation must have shape ({n}, {n}), got {self.correlation.shape}"
            )
        if self.initial_value < 0:
            raise ValueError("initial_value must not be negative")


@dataclass(frozen=True)
class SimulationConfig:
    horizon_days: int = 90
    simulations: int = 10_000
    seed: int | None = None
    drift_mode: DriftMode = DriftMode.ZERO
    drift_shrinkage: float = 0.25
    volatility_multiplier: float = 1.0
    antithetic: bool = True

    def __post_init__(self) -> None:
        if self.horizon_days < 1:
            raise ValueError("horizon_days must be at least 1")
        if self.simulations < 2:
            raise ValueError("simulations must be at least 2")
        if self.volatility_multiplier <= 0:
            raise ValueError("volatility_multiplier must be positive")


@dataclass
class SimulationOutput:
    """Raw engine output. The API layer shapes this into response models."""

    initial_value: float
    horizon_days: int
    simulations: int

    terminal_values: np.ndarray
    drawdowns: np.ndarray
    percentiles: dict[int, np.ndarray] = field(default_factory=dict)

    expected_value: float = 0.0
    median_value: float = 0.0
    best_case: float = 0.0
    worst_case: float = 0.0
    p5: float = 0.0
    p95: float = 0.0
    probability_of_loss: float = 0.0
    expected_drawdown: float = 0.0
    max_drawdown_p95: float = 0.0
    expected_return: float = 0.0
    volatility_of_outcomes: float = 0.0

    def histogram(self, bins: int = 40) -> list[tuple[float, float, int]]:
        """Terminal value distribution as (lower, upper, count) triples."""
        if self.terminal_values.size == 0:
            return []
        counts, edges = np.histogram(self.terminal_values, bins=bins)
        return [
            (float(edges[i]), float(edges[i + 1]), int(counts[i]))
            for i in range(len(counts))
        ]


def resolve_drift(inputs: SimulationInputs, config: SimulationConfig) -> np.ndarray:
    """Annualised log drift per asset for the selected mode.

    ZERO       expected simple return of zero, i.e. a driftless market
    HISTORICAL the realised mean log return over the estimation window
    SHRUNK     the historical estimate pulled towards zero, which tempers the
               noise in a short sample without discarding it entirely
    """
    variance = inputs.volatilities**2

    if config.drift_mode is DriftMode.ZERO or inputs.historical_drift is None:
        return -0.5 * variance

    historical = np.asarray(inputs.historical_drift, dtype=float)

    if config.drift_mode is DriftMode.HISTORICAL:
        return historical

    shrinkage = float(np.clip(config.drift_shrinkage, 0.0, 1.0))
    return shrinkage * historical + (1.0 - shrinkage) * (-0.5 * variance)


def _cholesky(correlation: np.ndarray) -> np.ndarray:
    """Cholesky factor of the correlation matrix, repaired if necessary."""
    if correlation.size == 0:
        return correlation
    repaired = nearest_positive_definite(correlation)
    try:
        return np.linalg.cholesky(repaired)
    except np.linalg.LinAlgError:
        # Last resort: treat the assets as independent rather than fail. This
        # understates joint risk, so it is a fallback and not a default.
        return np.eye(correlation.shape[0])


def simulate(inputs: SimulationInputs, config: SimulationConfig) -> SimulationOutput:
    """Run the simulation and summarise the resulting distribution."""
    n_assets = len(inputs.symbols)
    horizon = config.horizon_days
    n_sims = config.simulations

    if n_assets == 0 or inputs.initial_value <= 0:
        empty = np.zeros(0)
        return SimulationOutput(
            initial_value=inputs.initial_value,
            horizon_days=horizon,
            simulations=0,
            terminal_values=empty,
            drawdowns=empty,
        )

    rng = np.random.default_rng(config.seed)

    dt = 1.0 / TRADING_DAYS
    sigma = np.asarray(inputs.volatilities, dtype=float) * config.volatility_multiplier
    drift = resolve_drift(inputs, config)

    # Per-step log-return parameters.
    step_drift = drift * dt
    step_sigma = sigma * np.sqrt(dt)

    factor = _cholesky(inputs.correlation)
    weights = np.asarray(inputs.weights, dtype=float)

    # Portfolio value at each step, including day 0. This is the only array
    # that grows with the simulation count.
    values = np.empty((n_sims, horizon + 1), dtype=np.float64)
    values[:, 0] = inputs.initial_value

    # Capital allocated to each asset at the start.
    initial_allocation = inputs.initial_value * weights

    for start in range(0, n_sims, BATCH_SIZE):
        size = min(BATCH_SIZE, n_sims - start)
        shocks = _draw_shocks(rng, size, horizon, n_assets, config.antithetic)

        # Correlate the independent normals: (batch, horizon, assets) @ Lᵀ
        correlated = shocks @ factor.T

        log_steps = step_drift + step_sigma * correlated
        cumulative = np.cumsum(log_steps, axis=1)

        # Buy and hold: each asset's capital compounds independently and the
        # portfolio is their sum. No rebalancing occurs inside the horizon.
        asset_values = initial_allocation * np.exp(cumulative)
        values[start : start + size, 1:] = asset_values.sum(axis=2)

    return _summarise(values, inputs.initial_value, horizon, n_sims)


def _draw_shocks(
    rng: np.random.Generator,
    size: int,
    horizon: int,
    n_assets: int,
    antithetic: bool,
) -> np.ndarray:
    """Independent standard normals, optionally antithetically paired."""
    if not antithetic:
        return rng.standard_normal((size, horizon, n_assets))

    half = (size + 1) // 2
    base = rng.standard_normal((half, horizon, n_assets))
    paired = np.concatenate([base, -base], axis=0)
    return paired[:size]


def _summarise(
    values: np.ndarray, initial_value: float, horizon: int, n_sims: int
) -> SimulationOutput:
    """Collapse simulated value paths into the reported statistics."""
    terminal = values[:, -1]

    # Peak-to-trough decline within each path.
    running_peak = np.maximum.accumulate(values, axis=1)
    drawdowns = np.max((running_peak - values) / running_peak, axis=1)

    percentile_levels = [5, 25, 50, 75, 95]
    bands = np.percentile(values, percentile_levels, axis=0)
    percentiles = {
        level: bands[index] for index, level in enumerate(percentile_levels)
    }

    return SimulationOutput(
        initial_value=initial_value,
        horizon_days=horizon,
        simulations=n_sims,
        terminal_values=terminal,
        drawdowns=drawdowns,
        percentiles=percentiles,
        expected_value=float(terminal.mean()),
        median_value=float(np.median(terminal)),
        best_case=float(terminal.max()),
        worst_case=float(terminal.min()),
        p5=float(np.percentile(terminal, 5)),
        p95=float(np.percentile(terminal, 95)),
        probability_of_loss=float((terminal < initial_value).mean()),
        expected_drawdown=float(drawdowns.mean()),
        max_drawdown_p95=float(np.percentile(drawdowns, 95)),
        expected_return=float(terminal.mean() / initial_value - 1.0),
        volatility_of_outcomes=float(terminal.std(ddof=1) / initial_value),
    )


def simulate_allocation(
    inputs: SimulationInputs,
    config: SimulationConfig,
    stablecoin_ratio: float,
    stable_mask: np.ndarray,
) -> SimulationOutput:
    """Re-run the simulation with the book shifted to a target stablecoin ratio.

    Volatile weights are scaled down proportionally and the freed capital is
    distributed across the stable assets by their existing relative weight.
    This is what powers scenario comparison: identical market draws, different
    allocation.
    """
    weights = np.asarray(inputs.weights, dtype=float).copy()
    ratio = float(np.clip(stablecoin_ratio, 0.0, 1.0))

    stable_total = weights[stable_mask].sum()
    volatile_total = weights[~stable_mask].sum()

    if stable_mask.any() and stable_total > 0:
        weights[stable_mask] = weights[stable_mask] / stable_total * ratio
    elif stable_mask.any():
        # No existing stable position to scale: spread evenly.
        weights[stable_mask] = ratio / stable_mask.sum()
    elif ratio > 0:
        raise ValueError("cannot target a stablecoin ratio without a stable asset")

    if volatile_total > 0:
        weights[~stable_mask] = weights[~stable_mask] / volatile_total * (1.0 - ratio)

    total = weights.sum()
    if total > 0:
        weights = weights / total

    shifted = SimulationInputs(
        symbols=inputs.symbols,
        weights=weights,
        volatilities=inputs.volatilities,
        correlation=inputs.correlation,
        initial_value=inputs.initial_value,
        historical_drift=inputs.historical_drift,
    )

    return simulate(shifted, config)
