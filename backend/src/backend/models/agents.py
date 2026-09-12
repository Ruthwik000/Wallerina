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


class Trade(BaseModel):
    """A proposed rebalancing leg. Recommendation only — never executed."""

    action: str
    symbol: str
    value_usd: float
    quantity: float | None = None
    reason: str


Recommendation.model_rebuild()
