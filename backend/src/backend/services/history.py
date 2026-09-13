"""Portfolio value and risk over time.

Two sources, kept apart because they answer different questions:

* **backfilled** — today's analysed holdings, held unchanged, valued over their
  price history. Available immediately for any wallet, but it shows what *this
  book* would have done, not what the wallet actually did.
* **recorded** — snapshots saved by the background refresh and by each
  recommendation. The wallet's real value over time, deposits and withdrawals
  included, but only since tracking began.
"""

from __future__ import annotations

import numpy as np

from backend.models.history import HistoryPoint, PerformanceHistory, RecordedRisk, RiskHistory
from backend.quant.risk import TRADING_DAYS

ROLLING_WINDOW_DAYS = 30


def backfilled_values(estimate) -> tuple[list[str], np.ndarray]:
    """Value of today's analysed positions on every day of their price history.

    Each position's value is walked back from today using its own log returns:
    a price on day j relative to the last day is exp(-sum of returns after j).
    """
    matrix = estimate.matrix
    if matrix.observations == 0 or len(matrix.days) != matrix.observations + 1:
        return [], np.empty(0)

    current = np.array([position.value_usd for position in estimate.positions], dtype=float)

    # remaining[j, i]: asset i's log return from day j to the last day.
    remaining = np.vstack(
        [np.cumsum(matrix.returns[::-1], axis=0)[::-1], np.zeros((1, matrix.n_assets))]
    )
    values = (current * np.exp(-remaining)).sum(axis=1)

    return list(matrix.days), values


def performance(estimate, recorded: list[dict]) -> PerformanceHistory:
    days, values = backfilled_values(estimate)

    total_return = (
        float(values[-1] / values[0] - 1.0) if values.size >= 2 and values[0] > 0 else None
    )

    return PerformanceHistory(
        backfilled=[HistoryPoint(t=day, v=round(float(value), 2)) for day, value in zip(days, values)],
        total_return=total_return,
        window_days=max(len(days) - 1, 0),
        recorded=[HistoryPoint(t=row["t"], v=row["value_usd"]) for row in recorded],
        excluded=list(estimate.excluded),
    )


def risk_history(estimate, recorded: list[dict], window: int = ROLLING_WINDOW_DAYS) -> RiskHistory:
    days, values = backfilled_values(estimate)
    volatility: list[HistoryPoint] = []
    drawdown: list[HistoryPoint] = []

    if values.size >= 2:
        peaks = np.maximum.accumulate(values)
        drawdown = [
            HistoryPoint(t=day, v=round(float(1.0 - value / peak), 4))
            for day, value, peak in zip(days, values, peaks)
        ]

        # Return k runs from day k to day k+1, so a window ending at return
        # end-1 is dated days[end].
        book_returns = np.diff(np.log(values))
        for end in range(window, book_returns.size + 1):
            sample = book_returns[end - window : end]
            annualised = float(np.std(sample, ddof=1) * np.sqrt(TRADING_DAYS))
            volatility.append(HistoryPoint(t=days[end], v=round(annualised, 4)))

    return RiskHistory(
        rolling_window_days=window,
        volatility=volatility,
        drawdown=drawdown,
        recorded=[RecordedRisk(**row) for row in recorded],
    )
