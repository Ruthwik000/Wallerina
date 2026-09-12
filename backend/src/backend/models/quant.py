"""Risk and simulation schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AssetRisk(BaseModel):
    symbol: str
    weight: float
    annual_volatility: float
    risk_contribution: float = Field(
        description="Share of total portfolio volatility attributable to this asset, 0-1"
    )
    beta_to_portfolio: float
    max_drawdown: float
    observations: int


class RiskMetrics(BaseModel):
    """Historical risk of the portfolio as currently held."""

    portfolio_annual_volatility: float
    value_at_risk: float = Field(description="Historical VaR as a positive loss fraction")
    value_at_risk_usd: float
    expected_shortfall: float = Field(description="Mean loss beyond VaR, positive fraction")
    expected_shortfall_usd: float
    max_drawdown: float
    concentration: float
    downside_exposure: float = Field(
        description="Share of the book held in non-stable assets"
    )
    confidence: float
    observations: int
    assets: list[AssetRisk]
    correlation_symbols: list[str]
    correlation_matrix: list[list[float]]


class SimulationRequest(BaseModel):
    wallet_address: str
    horizon_days: int = Field(default=90, ge=1, le=1095)
    simulations: int = Field(default=10_000, ge=100, le=200_000)
    stablecoin_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override the held allocation to test a different stablecoin weight",
    )
    seed: int | None = None
    use_prediction_markets: bool = True


class PercentileBand(BaseModel):
    day: int
    p5: float
    p25: float
    median: float
    p75: float
    p95: float


class DistributionBin(BaseModel):
    lower: float
    upper: float
    count: int


class ScenarioResult(BaseModel):
    name: str
    stablecoin_ratio: float
    expected_value: float
    median_value: float
    p5: float
    expected_drawdown: float
    probability_of_loss: float


class SimulationResult(BaseModel):
    """Output of the Monte Carlo engine."""

    initial_value: float
    horizon_days: int
    simulations: int

    expected_value: float
    median_value: float
    best_case: float
    worst_case: float
    p5: float
    p95: float

    probability_of_loss: float
    expected_drawdown: float
    max_drawdown_p95: float = Field(
        description="Drawdown exceeded by only 5% of simulated paths"
    )

    expected_return: float
    volatility_of_outcomes: float

    fan: list[PercentileBand]
    distribution: list[DistributionBin]

    stablecoin_ratio: float
    drift_mode: str
    volatility_multiplier: float
    seed: int | None
