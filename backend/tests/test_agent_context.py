"""The goal agent's context reaches every downstream agent, unchanged."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents import analysts, goal as goal_layer, judgement, llm, pipeline
from backend.aws import telemetry
from backend.core.config import get_settings
from backend.models.agents import AgentReport, Judgement
from backend.models.goal import GoalType
from backend.models.market import MarketStress
from backend.models.quant import RiskMetrics, SimulationResult
from backend.services import analysis
from backend.services.http import UpstreamError
from tests.test_allocation import decide

WALLET = "0x" + "a" * 40


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("RDS_HOST", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestBuildContext:
    @pytest.mark.asyncio
    async def test_preset_builds_context_without_a_model(self, monkeypatch):
        async def forbidden(**kwargs):
            raise AssertionError("a preset goal must not call the model")

        monkeypatch.setattr(llm, "structured", forbidden)

        context = await goal_layer.build_context(WALLET, "Preserve capital")

        preset = goal_layer.PRESETS[GoalType.CAPITAL_PRESERVATION]
        assert context.intent.goal_type is GoalType.CAPITAL_PRESERVATION
        assert context.rules.maximum_drawdown == preset["maximum_drawdown"]
        assert context.rules.base_stablecoin_ratio == preset["base_stablecoin_ratio"]
        assert context.goal == "Preserve capital"

    @pytest.mark.asyncio
    async def test_horizon_override_is_written_into_the_rules(self):
        context = await goal_layer.build_context(WALLET, "balanced", horizon_days=30)

        assert context.rules.time_horizon_days == 30
        assert context.horizon_days == 30

    @pytest.mark.asyncio
    async def test_free_text_rules_come_from_the_model_intent(self, monkeypatch):
        monkeypatch.setattr(llm, "configured", lambda: True)

        async def structured(**kwargs):
            return {
                "goal_type": "growth",
                "risk_tolerance": "high",
                "maximum_drawdown": 0.15,
                "time_horizon_days": 180,
                "interpretation": "Growth, but no more than a 15% loss.",
            }

        monkeypatch.setattr(llm, "structured", structured)

        context = await goal_layer.build_context(WALLET, "Grow but never lose over 15%")

        assert context.intent.source == "llm"
        assert context.rules.maximum_drawdown == 0.15
        # A 15% limit lifts the growth floor, which every agent then inherits.
        assert context.rules.minimum_stablecoin_ratio == 0.20


def _risk() -> RiskMetrics:
    return RiskMetrics.model_construct(
        portfolio_annual_volatility=0.6,
        value_at_risk=0.05,
        value_at_risk_usd=500.0,
        expected_shortfall=0.07,
        observations=180,
        assets=[],
    )


def _simulation(drawdown: float) -> SimulationResult:
    return SimulationResult.model_construct(
        horizon_days=90, expected_drawdown=drawdown, max_drawdown_p95=drawdown * 2
    )


class TestAgentsJudgeAgainstTheGoal:
    def test_same_drawdown_rates_differently_by_goal(self):
        aggressive = goal_layer.context_for(WALLET, "aggressive growth", goal_layer.preset_intent(GoalType.AGGRESSIVE_GROWTH))
        cautious = goal_layer.context_for(WALLET, "preserve capital", goal_layer.preset_intent(GoalType.CAPITAL_PRESERVATION))

        def drawdown_severity(context):
            report = analysts.analyse_market(context, _risk(), None, 0.5, _simulation(0.12))
            return next(f for f in report.findings if f.label == "Drawdown against goal").severity

        assert drawdown_severity(aggressive) == "low"
        assert drawdown_severity(cautious) == "high"


@pytest.fixture
def graph_services(monkeypatch):
    """Stub every service the graph touches; records what each agent saw."""
    seen: dict[str, object] = {"horizons": [], "load_calls": 0}

    portfolio = SimpleNamespace(stablecoin_ratio=0.1, concentration=0.5, model_dump=lambda **_: {})
    estimate = SimpleNamespace(
        correlation=[[1.0, 0.8], [0.8, 1.0]],
        stable_mask=np.array([False, False]),
        total_value=10_000.0,
    )

    async def load_estimate(address):
        seen["load_calls"] += 1
        return portfolio, estimate

    async def load_market_stress(_):
        return MarketStress.model_construct(available=False, score=0.0)

    def run_simulation(*args, horizon_days, **kwargs):
        seen["horizons"].append(horizon_days)
        return _simulation(0.1)

    monkeypatch.setattr(analysis, "load_estimate", load_estimate)
    monkeypatch.setattr(analysis, "load_market_stress", load_market_stress)
    monkeypatch.setattr(analysis, "compute_risk", lambda *a: _risk())
    monkeypatch.setattr(analysis, "run_simulation", run_simulation)
    decision = decide()  # built before allocation.decide is patched below

    def spy_decide(**kwargs):
        seen["rules"] = kwargs["rules"]
        return decision

    monkeypatch.setattr(pipeline.allocation, "decide", spy_decide)
    monkeypatch.setattr(telemetry, "record_recommendation", lambda *a: None)

    def spy(name):
        def agent(context, *args):
            seen[name] = context
            return AgentReport(agent=name, headline="", findings=[])

        return agent

    async def explain(context, decision, reports):
        seen["judgement"] = context
        seen["reports"] = reports
        return Judgement(summary="s", reasoning=["r"], caveats=["c"], used_model=False)

    monkeypatch.setattr(analysts, "analyse_wallet", spy("wallet"))
    monkeypatch.setattr(analysts, "analyse_market", spy("market"))
    monkeypatch.setattr(analysts, "analyse_stablecoins", spy("stablecoin"))
    monkeypatch.setattr(judgement, "explain", explain)
    seen["load_estimate"] = load_estimate
    return seen


class TestPipelineGraph:
    @pytest.mark.asyncio
    async def test_a_crashing_analysis_agent_degrades_the_run(self, monkeypatch, graph_services):
        def broken(*args):
            raise RuntimeError("boom")

        monkeypatch.setattr(analysts, "analyse_stablecoins", broken)

        result = await pipeline.recommend(WALLET, "balanced")

        assert [r.agent for r in result.reports] == ["wallet", "market", "stablecoin"]
        assert result.reports[2].headline == "Analysis unavailable"
        assert result.warnings == ["stablecoin agent failed: boom"]
        assert graph_services["judgement"] is not None, "the explanation still ran"

    @pytest.mark.asyncio
    async def test_upstream_failures_are_retried(self, monkeypatch, graph_services):
        succeed = graph_services["load_estimate"]
        attempts = {"n": 0}

        async def flaky(address):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise UpstreamError("alchemy", "rate limited", 429)
            return await succeed(address)

        monkeypatch.setattr(analysis, "load_estimate", flaky)

        result = await pipeline.recommend(WALLET, "balanced")

        assert attempts["n"] == 2
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_data_errors_are_not_retried(self, monkeypatch, graph_services):
        attempts = {"n": 0}

        async def empty(address):
            attempts["n"] += 1
            raise analysis.InsufficientDataError("no priced holdings")

        monkeypatch.setattr(analysis, "load_estimate", empty)

        with pytest.raises(analysis.InsufficientDataError):
            await pipeline.recommend(WALLET, "balanced")
        assert attempts["n"] == 1

    @pytest.mark.asyncio
    async def test_every_agent_receives_the_same_context(self, graph_services):
        seen = graph_services
        result = await pipeline.recommend(WALLET, "Preserve capital", horizon_days=45)

        context = seen["wallet"]
        assert seen["market"] is context
        assert seen["stablecoin"] is context
        assert seen["judgement"] is context
        assert seen["rules"] is context.rules, "the allocation engine uses the context's rules"
        assert seen["horizons"] == [45], "the simulator runs on the context's horizon"
        assert result.rules == context.rules
        assert result.goal == "Preserve capital"
