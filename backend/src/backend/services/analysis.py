"""Analysis orchestration: wallet -> prices -> risk -> simulation.

This is the deterministic half of the pipeline in specification section 3.
The agent and allocation-decision layers are deliberately not implemented
here; this module stops once the quantitative evidence has been produced.
"""

from __future__ import annotations

import logging

import numpy as np

from backend.assets.registry import AssetClass
from backend.core.config import get_settings
from backend.models.market import MarketStress, PriceHistory
from backend.models.portfolio import Holding, Portfolio
from backend.models.quant import (
    AssetRisk,
    DistributionBin,
    PercentileBand,
    RiskMetrics,
    ScenarioResult,
    SimulationResult,
)
from backend.quant import risk as risk_engine
from backend.quant.monte_carlo import (
    DriftMode,
    SimulationConfig,
    SimulationInputs,
    simulate,
    simulate_allocation,
)
from backend.quant.risk import TRADING_DAYS, ReturnMatrix
from backend.services.cache import analysis_cache
from backend.services.polymarket import client as polymarket
from backend.services.wallet import alchemy

logger = logging.getLogger(__name__)


class InsufficientDataError(RuntimeError):
    """Not enough usable history to produce a quantitative result."""


# --------------------------------------------------------------------------
# Position aggregation
# --------------------------------------------------------------------------


class Position:
    """One economic exposure, summed across the chains it is held on.

    ETH on Ethereum, Base and Arbitrum is a single exposure to the price of
    ETH; simulating it as three independent assets would understate
    concentration and overstate diversification.
    """

    def __init__(self, symbol: str, classification: AssetClass):
        self.symbol = symbol
        self.classification = classification
        self.value_usd = 0.0
        self.quantity = 0.0

    @property
    def is_stable(self) -> bool:
        return self.classification is AssetClass.STABLECOIN


def aggregate_positions(holdings: list[Holding]) -> list[Position]:
    positions: dict[str, Position] = {}

    for holding in holdings:
        position = positions.get(holding.symbol)
        if position is None:
            position = Position(holding.symbol, holding.classification)
            positions[holding.symbol] = position
        position.value_usd += holding.value_usd
        position.quantity += holding.quantity

    return sorted(positions.values(), key=lambda p: -p.value_usd)


# --------------------------------------------------------------------------
# Estimation
# --------------------------------------------------------------------------


class EstimationResult:
    """Parameters estimated from history, aligned to a set of positions."""

    def __init__(
        self,
        positions: list[Position],
        matrix: ReturnMatrix,
        weights: np.ndarray,
        volatilities: np.ndarray,
        correlation: np.ndarray,
        drift: np.ndarray,
        total_value: float,
        excluded: list[str],
    ):
        self.positions = positions
        self.matrix = matrix
        self.weights = weights
        self.volatilities = volatilities
        self.correlation = correlation
        self.drift = drift
        self.total_value = total_value
        self.excluded = excluded

    @property
    def symbols(self) -> list[str]:
        return [position.symbol for position in self.positions]

    @property
    def stable_mask(self) -> np.ndarray:
        return np.array([position.is_stable for position in self.positions])

    @property
    def stablecoin_ratio(self) -> float:
        mask = self.stable_mask
        return float(self.weights[mask].sum()) if mask.any() else 0.0


def estimate_parameters(
    portfolio: Portfolio, histories: dict[str, PriceHistory]
) -> EstimationResult:
    """Estimate weights, volatility, correlation and drift from history.

    Positions without usable history are excluded and the remaining weights
    renormalised, because a simulated asset needs a volatility estimate. The
    excluded symbols are reported so the caller can surface the gap.
    """
    positions = aggregate_positions(portfolio.holdings)

    usable: list[Position] = []
    excluded: list[str] = []
    price_series: dict[str, list[tuple[str, float]]] = {}

    for position in positions:
        history = histories.get(position.symbol)
        if history is None or len(history.points) < 3:
            excluded.append(position.symbol)
            continue
        usable.append(position)
        price_series[position.symbol] = [
            (point.timestamp, point.value) for point in history.points
        ]

    if not usable:
        raise InsufficientDataError(
            "No holding has enough price history to estimate risk"
        )

    matrix, short_history = risk_engine.align_histories(price_series)
    excluded.extend(short_history)

    if matrix.observations < 2:
        raise InsufficientDataError(
            f"Only {matrix.observations} overlapping observations across holdings"
        )

    # align_histories sorts symbols and may have dropped short series; keep
    # only the surviving positions and put them in the matrix's index order so
    # every array in this module shares one ordering.
    order = {symbol: index for index, symbol in enumerate(matrix.symbols)}
    usable = [position for position in usable if position.symbol in order]
    usable.sort(key=lambda position: order[position.symbol])

    if not usable:
        raise InsufficientDataError("No holding retained enough overlapping history")

    total = sum(position.value_usd for position in usable)
    weights = np.array([position.value_usd / total for position in usable])

    volatilities = risk_engine.annualised_volatility(matrix.returns)
    correlation = risk_engine.correlation_matrix(matrix.returns)
    drift = matrix.returns.mean(axis=0) * TRADING_DAYS

    return EstimationResult(
        positions=usable,
        matrix=matrix,
        weights=weights,
        volatilities=volatilities,
        correlation=correlation,
        drift=drift,
        total_value=total,
        excluded=excluded,
    )


# --------------------------------------------------------------------------
# Risk
# --------------------------------------------------------------------------


def compute_risk(
    portfolio: Portfolio, estimate: EstimationResult, confidence: float | None = None
) -> RiskMetrics:
    """Historical risk metrics for the book as currently held."""
    settings = get_settings()
    confidence = confidence if confidence is not None else settings.var_confidence

    returns = estimate.matrix.returns
    weights = estimate.weights

    portfolio_series = risk_engine.portfolio_returns(returns, weights)
    contributions, portfolio_volatility = risk_engine.risk_contributions(weights, returns)
    asset_betas = risk_engine.betas(weights, returns)

    var = risk_engine.historical_var(portfolio_series, confidence)
    shortfall = risk_engine.expected_shortfall(portfolio_series, confidence)

    assets = [
        AssetRisk(
            symbol=position.symbol,
            weight=float(weights[index]),
            annual_volatility=float(estimate.volatilities[index]),
            risk_contribution=float(contributions[index]),
            beta_to_portfolio=float(asset_betas[index]),
            max_drawdown=risk_engine.max_drawdown(returns[:, index]),
            observations=estimate.matrix.observations,
        )
        for index, position in enumerate(estimate.positions)
    ]

    return RiskMetrics(
        portfolio_annual_volatility=portfolio_volatility,
        value_at_risk=var,
        value_at_risk_usd=var * portfolio.total_value_usd,
        expected_shortfall=shortfall,
        expected_shortfall_usd=shortfall * portfolio.total_value_usd,
        max_drawdown=risk_engine.max_drawdown(portfolio_series),
        concentration=risk_engine.concentration(weights),
        downside_exposure=portfolio.volatile_ratio,
        confidence=confidence,
        observations=estimate.matrix.observations,
        assets=sorted(assets, key=lambda asset: -asset.risk_contribution),
        correlation_symbols=estimate.symbols,
        correlation_matrix=[
            [float(value) for value in row] for row in estimate.correlation
        ],
    )


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------


def build_simulation_inputs(
    estimate: EstimationResult, initial_value: float
) -> SimulationInputs:
    return SimulationInputs(
        symbols=estimate.symbols,
        weights=estimate.weights,
        volatilities=estimate.volatilities,
        correlation=estimate.correlation,
        initial_value=initial_value,
        historical_drift=estimate.drift,
    )


def _to_result(
    output,
    *,
    stablecoin_ratio: float,
    drift_mode: DriftMode,
    volatility_multiplier: float,
    seed: int | None,
) -> SimulationResult:
    """Shape raw engine output into the API response model."""
    fan = [
        PercentileBand(
            day=day,
            p5=float(output.percentiles[5][day]),
            p25=float(output.percentiles[25][day]),
            median=float(output.percentiles[50][day]),
            p75=float(output.percentiles[75][day]),
            p95=float(output.percentiles[95][day]),
        )
        for day in range(output.horizon_days + 1)
    ]

    distribution = [
        DistributionBin(lower=lower, upper=upper, count=count)
        for lower, upper, count in output.histogram()
    ]

    return SimulationResult(
        initial_value=output.initial_value,
        horizon_days=output.horizon_days,
        simulations=output.simulations,
        expected_value=output.expected_value,
        median_value=output.median_value,
        best_case=output.best_case,
        worst_case=output.worst_case,
        p5=output.p5,
        p95=output.p95,
        probability_of_loss=output.probability_of_loss,
        expected_drawdown=output.expected_drawdown,
        max_drawdown_p95=output.max_drawdown_p95,
        expected_return=output.expected_return,
        volatility_of_outcomes=output.volatility_of_outcomes,
        fan=fan,
        distribution=distribution,
        stablecoin_ratio=stablecoin_ratio,
        drift_mode=str(drift_mode),
        volatility_multiplier=volatility_multiplier,
        seed=seed,
    )


def run_simulation(
    estimate: EstimationResult,
    initial_value: float,
    *,
    horizon_days: int,
    simulations: int,
    seed: int | None = None,
    stress: MarketStress | None = None,
    stablecoin_ratio: float | None = None,
    drift_mode: DriftMode = DriftMode.ZERO,
) -> SimulationResult:
    multiplier = stress.volatility_multiplier if stress else 1.0

    config = SimulationConfig(
        horizon_days=horizon_days,
        simulations=simulations,
        seed=seed,
        drift_mode=drift_mode,
        volatility_multiplier=multiplier,
    )
    inputs = build_simulation_inputs(estimate, initial_value)

    if stablecoin_ratio is None:
        output = simulate(inputs, config)
        applied_ratio = estimate.stablecoin_ratio
    else:
        output = simulate_allocation(
            inputs, config, stablecoin_ratio, estimate.stable_mask
        )
        applied_ratio = stablecoin_ratio

    return _to_result(
        output,
        stablecoin_ratio=applied_ratio,
        drift_mode=drift_mode,
        volatility_multiplier=multiplier,
        seed=seed,
    )


def run_scenarios(
    estimate: EstimationResult,
    initial_value: float,
    *,
    horizon_days: int,
    simulations: int,
    ratios: list[float] | None = None,
    seed: int | None = None,
    stress: MarketStress | None = None,
) -> list[ScenarioResult]:
    """Compare stablecoin ratios under an identical set of market draws.

    Every scenario uses the same seed, so differences between them come from
    the allocation alone and not from sampling noise.
    """
    current = estimate.stablecoin_ratio

    if not estimate.stable_mask.any():
        # Without a stable asset there is nothing to rotate into.
        ratios = [current]
    elif ratios is None:
        # The current ratio is kept exact rather than rounded, so the scenario
        # that matches the book is recognisable as such below.
        candidates = [0.2, 0.4, 0.6, 0.8]
        ratios = sorted(
            [current]
            + [value for value in candidates if abs(value - current) > 0.01]
        )

    inputs = build_simulation_inputs(estimate, initial_value)
    config = SimulationConfig(
        horizon_days=horizon_days,
        simulations=simulations,
        seed=seed if seed is not None else 0,
        volatility_multiplier=stress.volatility_multiplier if stress else 1.0,
    )

    results: list[ScenarioResult] = []
    for ratio in ratios:
        output = simulate_allocation(inputs, config, ratio, estimate.stable_mask)
        name = (
            "Current allocation"
            if ratio == current
            else f"{ratio:.0%} stablecoin"
        )
        results.append(
            ScenarioResult(
                name=name,
                stablecoin_ratio=ratio,
                expected_value=output.expected_value,
                median_value=output.median_value,
                p5=output.p5,
                expected_drawdown=output.expected_drawdown,
                probability_of_loss=output.probability_of_loss,
            )
        )

    return results


# --------------------------------------------------------------------------
# Full pipeline
# --------------------------------------------------------------------------


async def load_estimate(
    address: str, days: int | None = None, use_cache: bool = True
) -> tuple[Portfolio, EstimationResult]:
    """Fetch the wallet and its price history, then estimate parameters.

    Cached per wallet: the underlying work is 20+ sequential provider calls,
    which no interactive client can afford to repeat on every page.
    """
    if not use_cache:
        return await _load_estimate_uncached(address, days)

    key = f"estimate:{address.lower()}:{days}"
    return await analysis_cache.get_or_compute(
        key, lambda: _load_estimate_uncached(address, days)
    )


async def _load_estimate_uncached(
    address: str, days: int | None = None
) -> tuple[Portfolio, EstimationResult]:
    portfolio = await alchemy.get_portfolio(address)

    if not portfolio.holdings:
        raise InsufficientDataError(
            "No priced holdings found for this wallet after spam and dust filtering"
        )

    histories = await alchemy.fetch_portfolio_history(portfolio.holdings, days=days)
    estimate = estimate_parameters(portfolio, histories)

    return portfolio, estimate


async def load_market_stress(estimate: EstimationResult) -> MarketStress:
    """Fetch prediction markets for the held assets and condense them.

    Polymarket is not required for the analysis to run: if it is unreachable
    the simulation proceeds with an unadjusted volatility estimate.
    """
    symbols = [
        position.symbol for position in estimate.positions if not position.is_stable
    ]

    try:
        markets = await polymarket.get_markets_for_assets(symbols)
    except Exception as error:
        logger.warning("Prediction-market data unavailable: %s", error)
        return MarketStress(
            score=0.0,
            volatility_multiplier=1.0,
            markets_considered=0,
            total_liquidity=0.0,
            available=False,
        )

    return polymarket.compute_market_stress(markets)
