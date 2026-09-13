"""Quantitative risk engine.

Pure NumPy over aligned historical price series. Nothing here calls the
network or knows about FastAPI, so every function is directly testable.

Conventions used throughout:

* returns are daily **log** returns
* volatility is annualised with 365 trading days, since crypto trades daily
* losses are reported as **positive** fractions (a VaR of 0.12 means a 12% loss)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRADING_DAYS = 365


@dataclass(frozen=True)
class ReturnMatrix:
    """Aligned daily log returns for a set of assets.

    ``returns`` has shape (observations, assets) and column ``i`` corresponds
    to ``symbols[i]``. ``days`` are the price dates the returns were taken
    between, so it holds one more entry than there are observations.
    """

    symbols: list[str]
    returns: np.ndarray
    days: tuple[str, ...] = ()

    @property
    def observations(self) -> int:
        return int(self.returns.shape[0])

    @property
    def n_assets(self) -> int:
        return int(self.returns.shape[1])


def log_returns(prices: np.ndarray) -> np.ndarray:
    """Daily log returns from a price series, dropping non-positive prices."""
    prices = np.asarray(prices, dtype=float)
    if prices.size < 2:
        return np.empty(0)
    safe = prices > 0
    if not safe.all():
        prices = prices[safe]
    if prices.size < 2:
        return np.empty(0)
    return np.diff(np.log(prices))


def align_histories(
    histories: dict[str, list[tuple[str, float]]], min_coverage: float = 0.6
) -> tuple[ReturnMatrix, list[str]]:
    """Build a return matrix from timestamped price series.

    Alignment is by **timestamp**, never by position. Providers drop the
    occasional day for thinly traded tokens, and aligning by index would slide
    one series against another from that point on -- which silently destroys
    the correlation estimate the simulator depends on, without any visible
    error.

    Series differ in length because tokens are listed at different times, so
    those covering less than ``min_coverage`` of the longest history are
    dropped rather than truncating every other asset down to their length.
    Dropped symbols are returned so the omission can be reported.
    """
    series: dict[str, dict[str, float]] = {}
    for symbol, points in histories.items():
        by_day = {
            timestamp[:10]: value
            for timestamp, value in points
            if value is not None and value > 0
        }
        if len(by_day) >= 2:
            series[symbol] = by_day

    if not series:
        return ReturnMatrix(symbols=[], returns=np.empty((0, 0))), []

    longest = max(len(values) for values in series.values())
    threshold = max(int(longest * min_coverage), 2)

    kept = {s: v for s, v in series.items() if len(v) >= threshold}
    dropped = sorted(s for s, v in series.items() if len(v) < threshold)

    if not kept:  # every series is short; use them all rather than give up
        kept, dropped = series, []

    # Only days on which every retained asset has a price can produce a
    # comparable cross-section of returns.
    common_days: set[str] | None = None
    for values in kept.values():
        days = set(values)
        common_days = days if common_days is None else common_days & days

    ordered_days = sorted(common_days or ())
    if len(ordered_days) < 2:
        return ReturnMatrix(symbols=[], returns=np.empty((0, 0))), dropped

    symbols = sorted(kept)
    prices = np.column_stack(
        [[kept[symbol][day] for day in ordered_days] for symbol in symbols]
    )

    # Returns are taken down each column of the date-aligned price matrix.
    matrix = np.diff(np.log(prices), axis=0)

    return ReturnMatrix(symbols=symbols, returns=matrix, days=tuple(ordered_days)), dropped


def annualised_volatility(returns: np.ndarray) -> np.ndarray:
    """Annualised volatility per column."""
    if returns.size == 0:
        return np.zeros(returns.shape[1] if returns.ndim == 2 else 0)
    return np.std(returns, axis=0, ddof=1) * np.sqrt(TRADING_DAYS)


def correlation_matrix(returns: np.ndarray) -> np.ndarray:
    """Pearson correlation, with zero-variance assets handled explicitly.

    A perfectly flat series (a stablecoin over a calm window) has undefined
    correlation; those rows become the identity rather than NaN.
    """
    n_assets = returns.shape[1]
    if n_assets == 0:
        return np.empty((0, 0))
    if returns.shape[0] < 2:
        return np.eye(n_assets)

    std = np.std(returns, axis=0, ddof=1)
    movers = std > 0

    corr = np.eye(n_assets)
    if movers.sum() >= 2:
        sub = np.corrcoef(returns[:, movers], rowvar=False)
        sub = np.nan_to_num(sub, nan=0.0)
        index = np.where(movers)[0]
        corr[np.ix_(index, index)] = sub

    np.fill_diagonal(corr, 1.0)
    return corr


def nearest_positive_definite(matrix: np.ndarray, epsilon: float = 1e-8) -> np.ndarray:
    """Project a correlation matrix onto the nearest positive-definite one.

    Sample correlations estimated from short windows are frequently not
    positive semi-definite, which makes the Cholesky factorisation the
    simulator needs fail. Clipping the eigenvalues and renormalising to a unit
    diagonal fixes that with a minimal change to the matrix.
    """
    if matrix.size == 0:
        return matrix

    symmetric = (matrix + matrix.T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)

    if (eigenvalues > epsilon).all():
        return symmetric

    clipped = eigenvectors @ np.diag(np.maximum(eigenvalues, epsilon)) @ eigenvectors.T

    # Renormalise back to a correlation matrix (unit diagonal).
    scale = np.sqrt(np.diag(clipped))
    scale[scale <= 0] = 1.0
    normalised = clipped / np.outer(scale, scale)
    np.fill_diagonal(normalised, 1.0)

    return normalised


def portfolio_returns(returns: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Portfolio return series for fixed weights."""
    if returns.size == 0:
        return np.empty(0)
    return returns @ weights


def historical_var(portfolio_series: np.ndarray, confidence: float = 0.95) -> float:
    """Historical Value at Risk as a positive loss fraction."""
    if portfolio_series.size == 0:
        return 0.0
    quantile = float(np.quantile(portfolio_series, 1.0 - confidence))
    return float(max(-np.expm1(quantile), 0.0))


def expected_shortfall(portfolio_series: np.ndarray, confidence: float = 0.95) -> float:
    """Mean loss in the tail beyond VaR, as a positive fraction."""
    if portfolio_series.size == 0:
        return 0.0
    cutoff = float(np.quantile(portfolio_series, 1.0 - confidence))
    tail = portfolio_series[portfolio_series <= cutoff]
    if tail.size == 0:
        return 0.0
    return float(max(-np.expm1(tail.mean()), 0.0))


def max_drawdown(returns: np.ndarray) -> float:
    """Largest peak-to-trough decline of a cumulative return series."""
    if returns.size == 0:
        return 0.0
    equity = np.exp(np.cumsum(returns))
    peak = np.maximum.accumulate(equity)
    return float(np.max((peak - equity) / peak))


def concentration(weights: np.ndarray) -> float:
    """Herfindahl-Hirschman index: 1/n for an equal book, 1.0 for a single asset."""
    if weights.size == 0:
        return 0.0
    return float(np.sum(weights**2))


def risk_contributions(
    weights: np.ndarray, returns: np.ndarray
) -> tuple[np.ndarray, float]:
    """Each asset's share of portfolio volatility, and that volatility.

    Uses the standard Euler decomposition: asset ``i`` contributes
    ``w_i * (Σw)_i / σ_p``, and the contributions sum to one.
    """
    if returns.size == 0 or weights.size == 0:
        return np.zeros(weights.size), 0.0

    covariance = np.cov(returns, rowvar=False, ddof=1)
    covariance = np.atleast_2d(covariance)

    variance = float(weights @ covariance @ weights)
    if variance <= 0:
        return np.zeros(weights.size), 0.0

    volatility = np.sqrt(variance)
    marginal = covariance @ weights
    contributions = weights * marginal / volatility

    total = contributions.sum()
    if total > 0:
        contributions = contributions / total

    return contributions, float(volatility * np.sqrt(TRADING_DAYS))


def betas(weights: np.ndarray, returns: np.ndarray) -> np.ndarray:
    """Beta of each asset against the portfolio itself."""
    if returns.size == 0:
        return np.zeros(weights.size)

    portfolio = portfolio_returns(returns, weights)
    variance = float(np.var(portfolio, ddof=1))
    if variance <= 0:
        return np.zeros(weights.size)

    centred_assets = returns - returns.mean(axis=0)
    centred_portfolio = portfolio - portfolio.mean()
    covariances = (centred_assets * centred_portfolio[:, None]).sum(axis=0) / (
        portfolio.size - 1
    )

    return covariances / variance
