"""The recommendation pipeline (specification section 3), as a LangGraph graph.

    START -> goal -> data -> simulate -+-> allocate   -+-> explain -> record -> END
                                       +-> wallet     -+
                                       +-> market     -+
                                       +-> stablecoin -+

* **goal** runs first and exactly once. Its ``AgentContext`` (intent plus the
  global rules) is written into the graph state, and every later node reads it
  from there; no downstream agent re-reads the goal or invents thresholds.
* **data** fetches the wallet, prices and prediction markets. It is the only
  node that talks to flaky upstreams, so it alone carries a retry policy.
* **allocate** and the three analysis agents run in parallel; ``explain`` waits
  for all four.
* An analysis agent that crashes degrades to a placeholder report plus a
  warning instead of failing the whole recommendation. The allocation engine
  is not protected that way: without a decision there is nothing to recommend.

Only two steps touch a language model: reading a free-text goal, and writing
the explanation. Both already fall back to deterministic output when the model
fails. Everything that produces a number is deterministic, which is what
specification section 2 requires.
"""

from __future__ import annotations

import logging
import operator
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

import numpy as np
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from backend.agents import analysts, goal as goal_layer, judgement
from backend.aws import database, telemetry
from backend.models.agents import AgentContext, AgentReport, Finding, Judgement, Recommendation, Trade
from backend.models.goal import AllocationDecision
from backend.models.market import MarketStress
from backend.models.quant import RiskMetrics, SimulationResult
from backend.quant import allocation
from backend.services import analysis
from backend.services.http import UpstreamError

logger = logging.getLogger(__name__)

# Paths used by the drawdown probe. Low enough to bisect quickly, high enough
# for the drawdown estimate to be stable.
PROBE_PATHS = 3_000

# Upstream providers fail transiently (rate limits, timeouts). Data errors such
# as InsufficientDataError are not retried: asking again will not help.
DATA_RETRY = RetryPolicy(max_attempts=3, initial_interval=0.5, backoff_factor=2.0, retry_on=UpstreamError)


class PipelineState(TypedDict, total=False):
    # Request
    address: str
    user_goal: str
    horizon_days: int | None
    explain: bool

    # Written by the goal agent; read by every node after it
    context: AgentContext

    # Evidence
    portfolio: Any
    estimate: Any
    stress: MarketStress
    risk: RiskMetrics
    simulation: SimulationResult
    correlation: float

    # Outputs — one key per parallel branch, so concurrent writes never collide
    decision: AllocationDecision
    wallet_report: AgentReport
    market_report: AgentReport
    stablecoin_report: AgentReport
    trades: list[Trade]
    judgement: Judgement | None
    recommendation: Recommendation

    # Appended to by any node; the reducer merges parallel branches
    warnings: Annotated[list[str], operator.add]


async def goal_node(state: PipelineState) -> dict:
    context = await goal_layer.build_context(
        state["address"], state["user_goal"], horizon_days=state.get("horizon_days")
    )
    rules = context.rules
    logger.info(
        "Goal context for %s: %s (%s), band %.2f-%.2f, drawdown limit %.2f, %s days",
        state["address"],
        context.intent.goal_type,
        context.intent.source,
        rules.minimum_stablecoin_ratio,
        rules.maximum_stablecoin_ratio,
        rules.maximum_drawdown,
        rules.time_horizon_days,
    )
    return {"context": context}


async def data_node(state: PipelineState) -> dict:
    portfolio, estimate = await analysis.load_estimate(state["address"])
    stress = await analysis.load_market_stress(estimate)
    risk = analysis.compute_risk(portfolio, estimate)
    return {"portfolio": portfolio, "estimate": estimate, "stress": stress, "risk": risk}


async def simulate_node(state: PipelineState) -> dict:
    estimate, stress = state["estimate"], state["stress"]
    simulation = analysis.run_simulation(
        estimate,
        estimate.total_value,
        horizon_days=state["context"].horizon_days,
        simulations=5_000,
        seed=7,
        stress=stress if stress.available else None,
    )
    correlation = allocation.mean_pairwise_correlation(
        np.asarray(estimate.correlation), estimate.stable_mask
    )
    return {"simulation": simulation, "correlation": correlation}


async def allocate_node(state: PipelineState) -> dict:
    context, estimate, stress = state["context"], state["estimate"], state["stress"]
    portfolio, risk = state["portfolio"], state["risk"]
    horizon = context.horizon_days

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
        rules=context.rules,
        current_stablecoin_ratio=portfolio.stablecoin_ratio,
        annual_volatility=risk.portfolio_annual_volatility,
        concentration=portfolio.concentration,
        correlation=state["correlation"],
        market_stress=stress.score if stress.available else None,
        observations=risk.observations,
        drawdown_probe=probe,
    )
    return {"decision": decision}


def _analysis_agent(name: str, run: Callable[[PipelineState], AgentReport]):
    """Wrap a deterministic analysis agent so a crash degrades, not fails."""
    key = f"{name}_report"

    async def node(state: PipelineState) -> dict:
        try:
            return {key: run(state)}
        except Exception as error:
            logger.exception("The %s agent failed", name)
            return {
                key: AgentReport(
                    agent=name,
                    headline="Analysis unavailable",
                    findings=[
                        Finding(
                            label="Agent failure",
                            detail=f"The {name} agent could not complete, so its evidence is missing from this recommendation",
                            severity="moderate",
                        )
                    ],
                ),
                "warnings": [f"{name} agent failed: {error}"],
            }

    return node


# The agents are looked up on their module at call time, so they can be swapped
# out in tests.
wallet_node = _analysis_agent(
    "wallet", lambda s: analysts.analyse_wallet(s["context"], s["portfolio"], s["risk"])
)
market_node = _analysis_agent(
    "market",
    lambda s: analysts.analyse_market(s["context"], s["risk"], s["stress"], s["correlation"], s["simulation"]),
)
stablecoin_node = _analysis_agent(
    "stablecoin", lambda s: analysts.analyse_stablecoins(s["context"], s["portfolio"])
)

ANALYSIS_NODES = ("wallet", "market", "stablecoin")


async def explain_node(state: PipelineState) -> dict:
    decision = state["decision"]
    reports = [state[f"{name}_report"] for name in ANALYSIS_NODES]

    trades = (
        analysts.propose_trades(state["portfolio"], state["risk"], decision.target_stablecoin_ratio)
        if decision.rebalance_required
        else []
    )
    verdict = (
        await judgement.explain(state["context"], decision, reports)
        if state.get("explain", True)
        else None
    )
    return {"trades": trades, "judgement": verdict}


async def record_node(state: PipelineState) -> dict:
    context, decision, address = state["context"], state["decision"], state["address"]

    recommendation = Recommendation(
        wallet_address=address,
        generated_at=datetime.now(UTC).isoformat(),
        goal=context.goal,
        intent=context.intent,
        rules=context.rules,
        decision=decision,
        reports=[state[f"{name}_report"] for name in ANALYSIS_NODES],
        judgement=state.get("judgement"),
        trades=state.get("trades", []),
        warnings=state.get("warnings", []),
    )

    telemetry.record_recommendation(decision.rebalance_required, decision.confidence)

    # Specification section 4: log every recommendation with its inputs. A
    # no-op without a database, and never raises, so it cannot fail the response.
    await database.save_snapshot(
        address, state["portfolio"].model_dump(mode="json"), state["risk"].model_dump(mode="json")
    )
    await database.save_recommendation(address, recommendation.model_dump(mode="json"))

    return {"recommendation": recommendation}


def build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("goal", goal_node)
    graph.add_node("data", data_node, retry_policy=DATA_RETRY)
    graph.add_node("simulate", simulate_node)
    graph.add_node("allocate", allocate_node)
    graph.add_node("wallet", wallet_node)
    graph.add_node("market", market_node)
    graph.add_node("stablecoin", stablecoin_node)
    graph.add_node("explain", explain_node)
    graph.add_node("record", record_node)

    graph.add_edge(START, "goal")
    graph.add_edge("goal", "data")
    graph.add_edge("data", "simulate")

    parallel = ["allocate", *ANALYSIS_NODES]
    for name in parallel:
        graph.add_edge("simulate", name)
    graph.add_edge(parallel, "explain")  # waits for all four branches

    graph.add_edge("explain", "record")
    graph.add_edge("record", END)

    return graph.compile()


GRAPH = build_graph()


async def recommend(
    address: str,
    user_goal: str = "balanced",
    *,
    horizon_days: int | None = None,
    explain: bool = True,
) -> Recommendation:
    """Produce a full recommendation for one wallet."""
    state = await GRAPH.ainvoke(
        {
            "address": address,
            "user_goal": user_goal,
            "horizon_days": horizon_days,
            "explain": explain,
            "warnings": [],
        }
    )
    return state["recommendation"]
