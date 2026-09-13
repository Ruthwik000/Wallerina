"""Agent output schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.models.goal import AllocationDecision, GoalIntent, PortfolioRules


class AgentContext(BaseModel):
    """The global context the goal agent builds once per run.

    Every downstream agent receives this same object, so the wallet, market,
    stablecoin and judgement agents all judge the evidence against one set of
    goal-derived rules rather than each forming its own idea of "too risky".
    """

    wallet_address: str
    goal: str = Field(description="The goal as the user stated or selected it")
    intent: GoalIntent
    rules: PortfolioRules

    @property
    def horizon_days(self) -> int:
        return self.rules.time_horizon_days


class Finding(BaseModel):
    """One observation from an analysis agent."""

    label: str
    detail: str
    severity: str = Field(description="low, moderate, elevated or high")


class AgentReport(BaseModel):
    agent: str
    headline: str
    findings: list[Finding]
    # Agents are deterministic unless stated; this records which ran on a model.
    used_model: bool = False


class GroundingReport(BaseModel):
    """The grounding agent's check of an explanation against the engine's figures."""

    grounded: bool = Field(description="Every figure in the final text came from the engine")
    figures_checked: int
    rejected: list[str] = Field(
        default_factory=list,
        description="Figures in the model's text that the engine never produced",
    )
    replaced_model_output: bool = False


class Judgement(BaseModel):
    """The judgement agent's explanation of an allocation it did not choose."""

    summary: str
    reasoning: list[str]
    caveats: list[str]
    used_model: bool
    grounding: GroundingReport | None = None


class Recommendation(BaseModel):
    """Everything the pipeline produced for one wallet."""

    wallet_address: str
    generated_at: str

    goal: str
    intent: GoalIntent
    rules: PortfolioRules
    decision: AllocationDecision

    reports: list[AgentReport]
    judgement: Judgement | None = None
    trades: list["Trade"] = Field(default_factory=list)
    holdings_after: list["PositionAfter"] = Field(
        default_factory=list,
        description="Every position kept after the proposed trades (all of them when no rebalance is needed)",
    )
    outlook: "RebalanceOutlook | None" = None
    warnings: list[str] = Field(
        default_factory=list,
        description="Agents that failed and were degraded rather than failing the run",
    )


class Trade(BaseModel):
    """A proposed rebalancing leg. Recommendation only — never executed."""

    action: str
    symbol: str
    value_usd: float
    quantity: float | None = None
    reason: str


class PositionAfter(BaseModel):
    """One position as it would stand after the proposed trades."""

    symbol: str
    classification: str
    value_before_usd: float
    value_after_usd: float
    ratio_after: float = Field(description="Share of today's portfolio value")
    action: str = Field(description="hold, reduce or increase")


class OutcomeSummary(BaseModel):
    """Monte Carlo outcome for one allocation of the book."""

    stablecoin_ratio: float
    expected_value: float
    median_value: float
    p5: float
    p95: float
    probability_of_loss: float
    expected_drawdown: float
    max_drawdown_p95: float
    expected_return: float
    volatility_of_outcomes: float


class RebalanceOutlook(BaseModel):
    """The book simulated as held and at the target, on identical market draws."""

    horizon_days: int
    simulations: int
    current: OutcomeSummary
    target: OutcomeSummary | None = None
    note: str | None = None


Recommendation.model_rebuild()
