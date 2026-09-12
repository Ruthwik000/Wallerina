"""Agent output schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.models.goal import AllocationDecision, GoalIntent, PortfolioRules


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


class Judgement(BaseModel):
    """The judgement agent's explanation of an allocation it did not choose."""

    summary: str
    reasoning: list[str]
    caveats: list[str]
    used_model: bool


class Recommendation(BaseModel):
    """Everything the pipeline produced for one wallet."""

    wallet_address: str
    generated_at: str

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
