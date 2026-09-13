"""Portfolio value and risk over time."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HistoryPoint(BaseModel):
    t: str = Field(description="ISO date or timestamp")
    v: float


class PerformanceHistory(BaseModel):
    backfilled: list[HistoryPoint] = Field(
        description="Today's analysed holdings, held unchanged, valued over their price history"
    )
    total_return: float | None = Field(
        description="Return of the backfilled series over its window, as a fraction"
    )
    window_days: int
    recorded: list[HistoryPoint] = Field(
        description="The wallet's actual value from saved snapshots, averaged into buckets"
    )
    excluded: list[str] = Field(
        description="Holdings left out of the backfill for lack of price history"
    )


class RecordedRisk(BaseModel):
    t: str
    annual_volatility: float
    value_at_risk: float
    max_drawdown: float


class RiskHistory(BaseModel):
    rolling_window_days: int
    volatility: list[HistoryPoint] = Field(
        description="Rolling annualised volatility of today's holdings, held unchanged"
    )
    drawdown: list[HistoryPoint] = Field(
        description="Drawdown from the running peak of the backfilled value, positive fraction"
    )
    recorded: list[RecordedRisk] = Field(
        description="Risk metrics saved with each snapshot, averaged into buckets"
    )
