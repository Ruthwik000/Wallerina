"""The recommendation pipeline (specification section 3).

Runs the flow end to end:

    goal -> rules -> wallet / market / stablecoin analysis
         -> quantitative risk -> Monte Carlo
         -> allocation engine (deterministic)
         -> judgement agent (explains only)

Only two steps touch a language model: reading a free-text goal, and writing
the explanation. Everything that produces a number is deterministic, which is
what specification section 2 requires.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import numpy as np

from backend.agents import analysts, goal as goal_layer, judgement
from backend.aws import database, telemetry
from backend.models.agents import Recommendation
from backend.models.goal import AllocationDecision, GoalIntent, PortfolioRules
from backend.quant import allocation
from backend.services import analysis

logger = logging.getLogger(__name__)

# Paths used by the drawdown probe. Low enough to bisect quickly, high enough
# for the drawdown estimate to be stable.
PROBE_PATHS = 3_000


async def recommend(
    address: str,
    user_goal: str = "balanced",
    *,
    horizon_days: int | None = None,
    explain: bool = True,
) -> Recommendation:
    """Produce a full recommendation for one wallet."""
    intent = await goal_layer.interpret(user_goal)
    rules = goal_layer.rules_for(intent)

    portfolio, estimate = await analysis.load_estimate(address)
    stress = await analysis.load_market_stress(estimate)
    risk = analysis.compute_risk(portfolio, estimate)

    horizon = horizon_days or rules.time_horizon_days

    simulation = analysis.run_simulation(
        estimate,
        estimate.total_value,
        horizon_days=horizon,
        simulations=5_000,
        seed=7,
        stress=stress if stress.available else None,
    )

    correlation = allocation.mean_pairwise_correlation(
        np.asarray(estimate.correlation), estimate.stable_mask
    )

    # The drawdown rule is enforced by asking the simulator directly: what
    # drawdown does this allocation actually produce? Only offered when the
    # book has a stable leg to rotate into.
    probe = None
    if estimate.stable_mask.any():

        def probe(candidate_ratio: float) -> float:
            result = analysis.run_simulation(
                estimate,
                estimate.total_value,
                horizon_days=horizon,
                simulations=PROBE_PATHS,
                seed=11,  # fixed, so the bisection is monotone and repeatable
                stablecoin_ratio=candidate_ratio,
            )
            return result.expected_drawdown

    decision = allocation.decide(
        rules=rules,
        current_stablecoin_ratio=portfolio.stablecoin_ratio,
        annual_volatility=risk.portfolio_annual_volatility,
        concentration=portfolio.concentration,
        correlation=correlation,
        market_stress=stress.score if stress.available else None,
        observations=risk.observations,
        drawdown_probe=probe,
    )

    reports = [
        analysts.analyse_wallet(portfolio, risk),
        analysts.analyse_market(risk, stress, correlation),
        analysts.analyse_stablecoins(portfolio),
    ]

    trades = (
        analysts.propose_trades(portfolio, risk, decision.target_stablecoin_ratio)
        if decision.rebalance_required
        else []
    )

    verdict = (
        await judgement.explain(intent, decision, reports) if explain else None
    )

    recommendation = Recommendation(
        wallet_address=address,
        generated_at=datetime.now(UTC).isoformat(),
        intent=intent,
        rules=rules,
        decision=decision,
        reports=reports,
        judgement=verdict,
        trades=trades,
    )

    telemetry.record_recommendation(decision.rebalance_required, decision.confidence)

    # Specification section 4: log every recommendation with its inputs. A
    # no-op without a database, so this never blocks the response.
    await database.save_snapshot(address, portfolio.model_dump(mode="json"), risk.model_dump(mode="json"))
    await database.save_recommendation(address, recommendation.model_dump(mode="json"))

    return recommendation
