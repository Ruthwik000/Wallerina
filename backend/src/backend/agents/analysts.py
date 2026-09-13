"""Analysis agents (specification section 3).

Wallet, market and stablecoin analysis. These are **deterministic**: each reads
the quantitative layer and reports findings. No model call is needed to observe
that two assets are correlated at 0.9, and using one would add latency, cost and
variance to a fact.

Each agent receives the goal agent's ``AgentContext`` and judges what it sees
against those rules: a 20% simulated drawdown is fine for aggressive growth and
a breach for capital preservation.

The model enters at the judgement step, where the job is genuinely linguistic.
"""

from __future__ import annotations

import numpy as np

from backend.assets.registry import AssetClass
from backend.models.agents import AgentContext, AgentReport, Finding, PositionAfter
from backend.models.goal import RiskTolerance
from backend.models.market import MarketStress
from backend.models.portfolio import Portfolio
from backend.models.quant import RiskMetrics, SimulationResult
from backend.quant.allocation import (
    CONCENTRATION_THRESHOLD,
    CORRELATION_THRESHOLD,
    REFERENCE_VOLATILITY,
)

# Peg tolerance before a stablecoin is treated as impaired.
PEG_WARN = 0.005
PEG_SERIOUS = 0.02


def _severity(value: float, moderate: float, elevated: float, high: float) -> str:
    if value >= high:
        return "high"
    if value >= elevated:
        return "elevated"
    if value >= moderate:
        return "moderate"
    return "low"


def analyse_wallet(
    context: AgentContext, portfolio: Portfolio, risk: RiskMetrics
) -> AgentReport:
    """Composition, concentration and where the risk actually sits."""
    rules = context.rules
    findings: list[Finding] = []

    # Goal fit: is the book inside the stablecoin band the goal allows?
    held = portfolio.stablecoin_ratio
    low, high = rules.minimum_stablecoin_ratio, rules.maximum_stablecoin_ratio
    gap = low - held if held < low else held - high if held > high else 0.0
    findings.append(
        Finding(
            label="Goal fit",
            detail=(
                f"{held:.0%} held in stablecoins against the {low:.0%}–{high:.0%} "
                f"band a {context.intent.goal_type.value.replace('_', ' ')} goal allows"
                + (
                    ""
                    if gap == 0
                    else f" — {gap:.0%} {'below the floor' if held < low else 'above the ceiling'}"
                )
            ),
            severity=_severity(gap, 0.001, rules.rebalance_threshold, 2 * rules.rebalance_threshold),
        )
    )

    findings.append(
        Finding(
            label="Composition",
            detail=(
                f"{portfolio.volatile_ratio:.0%} of ${portfolio.total_value_usd:,.0f} "
                f"sits in volatile or unrecognised assets, "
                f"{portfolio.stablecoin_ratio:.0%} in stablecoins, across "
                f"{len(portfolio.chains)} networks"
            ),
            severity=_severity(portfolio.volatile_ratio, 0.5, 0.75, 0.9),
        )
    )

    findings.append(
        Finding(
            label="Concentration",
            detail=(
                f"Herfindahl index {portfolio.concentration:.2f}"
                + (
                    " — the book is effectively a single position"
                    if portfolio.concentration > 0.8
                    else f" across {portfolio.holdings_kept} positions"
                )
            ),
            severity=_severity(portfolio.concentration, CONCENTRATION_THRESHOLD, 0.55, 0.8),
        )
    )

    # Risk contribution diverging from weight is the finding worth surfacing:
    # a small position can dominate the book's risk.
    if risk.assets:
        top = risk.assets[0]
        if top.risk_contribution > top.weight + 0.10:
            findings.append(
                Finding(
                    label="Risk concentration",
                    detail=(
                        f"{top.symbol} is {top.weight:.0%} of the book but carries "
                        f"{top.risk_contribution:.0%} of its risk, at "
                        f"{top.annual_volatility:.0%} volatility"
                    ),
                    severity="high" if top.risk_contribution > 0.6 else "elevated",
                )
            )

    unknown = [h for h in portfolio.holdings if h.classification is AssetClass.UNKNOWN]
    if unknown:
        findings.append(
            Finding(
                label="Unrecognised assets",
                detail=(
                    f"{len(unknown)} positions worth "
                    f"${portfolio.unknown_value_usd:,.0f} are not in the asset "
                    "registry and are counted as volatile exposure"
                ),
                severity=_severity(
                    portfolio.unknown_value_usd / max(portfolio.total_value_usd, 1),
                    0.05,
                    0.2,
                    0.4,
                ),
            )
        )

    if portfolio.scan_truncated:
        findings.append(
            Finding(
                label="Incomplete scan",
                detail=(
                    "The wallet holds more tokens than were scanned, so totals "
                    "may be understated"
                ),
                severity="moderate",
            )
        )

    return AgentReport(
        agent="wallet",
        headline=(
            f"${portfolio.total_value_usd:,.0f} across {portfolio.holdings_kept} "
            f"positions, {portfolio.volatile_ratio:.0%} of it volatile"
        ),
        findings=findings,
    )


def analyse_market(
    context: AgentContext,
    risk: RiskMetrics,
    stress: MarketStress | None,
    correlation: float,
    simulation: SimulationResult | None = None,
) -> AgentReport:
    """The risk environment the portfolio is sitting in."""
    limit = context.rules.maximum_drawdown
    findings: list[Finding] = []

    # The goal's drawdown limit is the yardstick for the simulated future.
    if simulation is not None:
        ratio = simulation.expected_drawdown / limit if limit else 0.0
        findings.append(
            Finding(
                label="Drawdown against goal",
                detail=(
                    f"Simulated expected drawdown over {simulation.horizon_days} days "
                    f"is {simulation.expected_drawdown:.1%} as held, against the "
                    f"{limit:.0%} limit set by the goal; 5% of paths fall "
                    f"{simulation.max_drawdown_p95:.1%} or more"
                ),
                severity=_severity(ratio, 0.6, 0.85, 1.0),
            )
        )

    gap = risk.portfolio_annual_volatility - REFERENCE_VOLATILITY
    findings.append(
        Finding(
            label="Volatility regime",
            detail=(
                f"Annualised volatility {risk.portfolio_annual_volatility:.0%}, "
                f"{abs(gap):.0%} {'above' if gap > 0 else 'below'} the "
                f"{REFERENCE_VOLATILITY:.0%} reference, measured over "
                f"{risk.observations} days"
            ),
            severity=_severity(risk.portfolio_annual_volatility, 0.45, 0.7, 1.0),
        )
    )

    findings.append(
        Finding(
            label="Correlation",
            detail=(
                f"Mean pairwise correlation across the volatile sleeve is "
                f"{correlation:.2f}"
                + (
                    " — these positions are one exposure, not several"
                    if correlation > CORRELATION_THRESHOLD
                    else " — the sleeve retains some genuine diversification"
                )
            ),
            severity=_severity(correlation, CORRELATION_THRESHOLD, 0.7, 0.85),
        )
    )

    findings.append(
        Finding(
            label="Tail risk",
            detail=(
                f"One-day Value at Risk {risk.value_at_risk:.1%} "
                f"(${risk.value_at_risk_usd:,.0f}); expected shortfall beyond it "
                f"{risk.expected_shortfall:.1%}"
            ),
            severity=_severity(risk.value_at_risk, 0.04, 0.08, 0.15),
        )
    )

    if stress is not None and stress.available:
        findings.append(
            Finding(
                label="Prediction markets",
                detail=(
                    f"Liquidity-weighted downside probability {stress.score:.0%} "
                    f"across {stress.markets_considered} active markets"
                ),
                severity=_severity(stress.score, 0.2, 0.4, 0.6),
            )
        )
    else:
        findings.append(
            Finding(
                label="Prediction markets",
                detail=(
                    "No prediction-market data available, so no external "
                    "corroboration was applied"
                ),
                severity="low",
            )
        )

    return AgentReport(
        agent="market",
        headline=(
            f"{_severity(risk.portfolio_annual_volatility, 0.45, 0.7, 1.0).title()} "
            f"volatility regime at {risk.portfolio_annual_volatility:.0%}"
        ),
        findings=findings,
    )


def analyse_stablecoins(context: AgentContext, portfolio: Portfolio) -> AgentReport:
    """Whether the safe half of the book is actually safe.

    Rotating into stablecoins is only risk reduction if the pegs hold and the
    issuers are diversified, so both are checked before any rebalance is
    proposed. A cautious goal leans on that leg harder, so the same weakness
    is rated more severely.
    """
    cautious = context.rules.risk_tolerance is RiskTolerance.LOW
    stables = [h for h in portfolio.holdings if h.classification is AssetClass.STABLECOIN]
    findings: list[Finding] = []

    if not stables:
        return AgentReport(
            agent="stablecoin",
            headline="No recognised stablecoin held",
            findings=[
                Finding(
                    label="No stable leg",
                    detail=(
                        "The wallet holds no stablecoin in the trusted registry, "
                        "so there is nothing to rotate into without acquiring one, "
                        f"yet the goal calls for at least "
                        f"{context.rules.minimum_stablecoin_ratio:.0%}"
                    ),
                    severity="high" if context.rules.minimum_stablecoin_ratio >= 0.25 else "elevated",
                )
            ],
        )

    worst_deviation = 0.0
    for holding in stables:
        deviation = abs(holding.price_usd - 1.0)
        worst_deviation = max(worst_deviation, deviation)
        if deviation >= PEG_WARN:
            findings.append(
                Finding(
                    label=f"{holding.symbol} peg",
                    detail=(
                        f"Trading at ${holding.price_usd:.4f}, "
                        f"{deviation * 100:.2f}% off peg"
                    ),
                    severity="high" if deviation >= PEG_SERIOUS else "elevated",
                )
            )

    if worst_deviation < PEG_WARN:
        findings.append(
            Finding(
                label="Peg stability",
                detail=(
                    f"All {len(stables)} stablecoin positions are within "
                    f"{PEG_WARN * 100:.1f}% of par"
                ),
                severity="low",
            )
        )

    issuers = {holding.symbol for holding in stables}
    total = portfolio.stablecoin_value_usd
    if total > 0 and len(issuers) == 1:
        findings.append(
            Finding(
                label="Issuer concentration",
                detail=(
                    f"The entire stable allocation sits in {next(iter(issuers))}; "
                    "a single issuer failure would affect all of it"
                ),
                severity="elevated" if cautious else "moderate",
            )
        )

    return AgentReport(
        agent="stablecoin",
        headline=(
            f"{len(issuers)} stablecoin issuers holding "
            f"${portfolio.stablecoin_value_usd:,.0f}, worst peg deviation "
            f"{worst_deviation * 100:.2f}%"
        ),
        findings=findings,
    )


def positions_after(portfolio: Portfolio, trades: list) -> list[PositionAfter]:
    """Every position that remains once the proposed trades are made.

    Positions are aggregated by symbol across networks, matching how trades
    name them. With no trades this is the book as held. Positions under 0.5%
    of the portfolio are left out, the same dust threshold trades use.
    """
    total = portfolio.total_value_usd
    if total <= 0:
        return []

    before: dict[str, float] = {}
    classes: dict[str, str] = {}
    for holding in portfolio.holdings:
        before[holding.symbol] = before.get(holding.symbol, 0.0) + holding.value_usd
        classes.setdefault(holding.symbol, AssetClass(holding.classification).value)

    after = dict(before)
    for trade in trades:
        change = trade.value_usd if trade.action == "buy" else -trade.value_usd
        after[trade.symbol] = after.get(trade.symbol, 0.0) + change

    dust = total * 0.005
    positions: list[PositionAfter] = []
    for symbol, value in after.items():
        value = max(value, 0.0)
        if value < dust:
            continue
        start = before.get(symbol, 0.0)
        if value > start + 0.01:
            action = "increase"
        elif value < start - 0.01:
            action = "reduce"
        else:
            action = "hold"
        positions.append(
            PositionAfter(
                symbol=symbol,
                classification=classes.get(symbol, AssetClass.UNKNOWN.value),
                value_before_usd=round(start, 2),
                value_after_usd=round(value, 2),
                ratio_after=value / total,
                action=action,
            )
        )

    return sorted(positions, key=lambda position: -position.value_after_usd)


def propose_trades(
    portfolio: Portfolio, risk: RiskMetrics, target_ratio: float
) -> list:
    """Legs that would move the book to the target ratio.

    Recommendation only — nothing here is ever executed. Sells are taken from
    the highest risk contributors first, which is where each dollar removed
    buys the most risk reduction.
    """
    from backend.models.agents import Trade

    total = portfolio.total_value_usd
    if total <= 0:
        return []

    delta = (target_ratio - portfolio.stablecoin_ratio) * total
    if abs(delta) < total * 0.01:
        return []

    trades: list[Trade] = []

    contribution = {asset.symbol: asset.risk_contribution for asset in risk.assets}

    if delta > 0:
        # Raising stablecoins: sell the worst risk contributors first.
        sellable = sorted(
            (h for h in portfolio.holdings if h.classification is not AssetClass.STABLECOIN),
            key=lambda h: (-contribution.get(h.symbol, 0.0), -h.value_usd),
        )
        remaining = delta
        for holding in sellable:
            if remaining <= 0:
                break
            amount = min(holding.value_usd, remaining)
            if amount < total * 0.005:
                continue
            remaining -= amount
            trades.append(
                Trade(
                    action="sell",
                    symbol=holding.symbol,
                    value_usd=round(amount, 2),
                    quantity=round(amount / holding.price_usd, 8)
                    if holding.price_usd
                    else None,
                    reason=(
                        f"Carries {contribution.get(holding.symbol, 0):.0%} of "
                        f"portfolio risk at {holding.portfolio_ratio:.0%} weight"
                    ),
                )
            )

        stables = [
            h for h in portfolio.holdings if h.classification is AssetClass.STABLECOIN
        ]
        bought = delta - max(remaining, 0)
        if stables and bought > 0:
            per_issuer = bought / len(stables)
            for holding in stables:
                trades.append(
                    Trade(
                        action="buy",
                        symbol=holding.symbol,
                        value_usd=round(per_issuer, 2),
                        reason="Spread across held issuers to avoid single-issuer risk",
                    )
                )
    else:
        # Lowering stablecoins: redeploy into the lowest-volatility volatile assets.
        stables = sorted(
            (h for h in portfolio.holdings if h.classification is AssetClass.STABLECOIN),
            key=lambda h: -h.value_usd,
        )
        remaining = -delta
        for holding in stables:
            if remaining <= 0:
                break
            amount = min(holding.value_usd, remaining)
            remaining -= amount
            trades.append(
                Trade(
                    action="sell",
                    symbol=holding.symbol,
                    value_usd=round(amount, 2),
                    reason="Reducing stablecoin weight toward the target",
                )
            )

    return trades
