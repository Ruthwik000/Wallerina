"""Goal and allocation schemas (specification sections 5-7)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class GoalType(StrEnum):
    AGGRESSIVE_GROWTH = "aggressive_growth"
    GROWTH = "growth"
    BALANCED = "balanced"
    SAVE_OVER_TIME = "save_over_time"
    CAPITAL_PRESERVATION = "capital_preservation"


class RiskTolerance(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class GoalIntent(BaseModel):
    """Structured intent extracted from what the user asked for."""

    goal_type: GoalType
    risk_tolerance: RiskTolerance
    maximum_drawdown: float = Field(ge=0.01, le=0.9)
    time_horizon_days: int | None = None
    source: str = Field(description="'preset' for the fast path, 'llm' for free text")
    interpretation: str | None = Field(
        default=None, description="How free-form text was read; null on the fast path"
    )


class PortfolioRules(BaseModel):
    """Global constraints the quantitative engine must respect (section 7)."""

    risk_tolerance: RiskTolerance
    base_stablecoin_ratio: float = Field(ge=0, le=1)
    minimum_stablecoin_ratio: float = Field(ge=0, le=1)
    maximum_stablecoin_ratio: float = Field(ge=0, le=1)
    maximum_drawdown: float = Field(ge=0, le=1)
    rebalance_threshold: float = Field(ge=0, le=1)
    time_horizon_days: int = Field(ge=1)


class AllocationDriver(BaseModel):
    """One named, bounded contribution to the target ratio.

    Every adjustment is recorded so the decision can be audited and explained
    without the explainer having to re-derive it.
    """

    name: str
    contribution: float = Field(description="Signed shift in the stablecoin ratio")
    detail: str


class AllocationDecision(BaseModel):
    """Output of the deterministic allocation engine.

    This is the authoritative allocation. No agent may alter these numbers;
    the judgement agent only explains them.
    """

    target_stablecoin_ratio: float = Field(ge=0, le=1)
    acceptable_range: tuple[float, float]
    current_stablecoin_ratio: float
    confidence: float = Field(ge=0, le=1)

    rebalance_required: bool
    drift: float = Field(description="Target minus current, signed")

    drivers: list[AllocationDriver]
    binding_constraint: str | None = Field(
        default=None,
        description="Which rule capped the result, if any",
    )
    drawdown_at_target: float | None = None
    rules: PortfolioRules
