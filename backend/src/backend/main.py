"""Wallerina FastAPI application.

Data retrieval, the quantitative engine, and the agent pipeline
(``/api/recommendation``): the goal agent builds a shared context, the wallet,
market and stablecoin agents analyse under it, the allocation engine decides,
and the judgement and grounding agents explain and verify.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.core.config import get_settings
from backend.agents import goal as goal_layer
from backend.agents import llm, pipeline
from backend.aws import database, secrets
from backend.models.agents import Recommendation
from backend.models.chat import ChatRequest
from backend.models.preferences import GoalRequest
from backend.models.market import AssetPredictionMarkets, MarketStress, PriceHistory
from backend.models.portfolio import Portfolio
from backend.models.quant import (
    RiskMetrics,
    ScenarioResult,
    SimulationRequest,
    SimulationResult,
)
from backend.services import analysis, chat, http, refresh
from backend.services.cache import analysis_cache
from backend.services.http import UpstreamError
from backend.services.polymarket import client as polymarket
from backend.services.wallet import alchemy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADDRESS_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Secrets Manager first: it may supply the API keys everything else needs.
    secrets.load_into_environment()
    await http.startup()
    await database.migrate()
    refresher = refresh.start()
    try:
        yield
    finally:
        await refresh.stop(refresher)
        await http.shutdown()
        await database.close()


app = FastAPI(
    title="Wallerina",
    description="Portfolio risk analysis and Monte Carlo simulation.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _handle(error: Exception) -> HTTPException:
    """Map internal failures onto meaningful HTTP responses."""
    if isinstance(error, analysis.InsufficientDataError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, chat.ChatUnavailableError):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(error, UpstreamError):
        return HTTPException(status_code=502, detail=str(error))
    return HTTPException(status_code=500, detail=str(error))


@app.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "alchemy_configured": settings.alchemy_configured,
        "model": llm.describe(),
        "aws_enabled": settings.aws_enabled,
        "database_configured": settings.database_configured,
        "networks": settings.alchemy_networks,
        "refresh": refresh.status,
    }


@app.get("/api/portfolio/{address}", response_model=Portfolio)
async def get_portfolio(address: str) -> Portfolio:
    """Classified, priced holdings for a wallet across supported networks."""
    try:
        return await alchemy.get_portfolio(address)
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/prices/history", response_model=PriceHistory)
async def get_price_history(
    symbol: str | None = None,
    network: str | None = None,
    address: str | None = None,
    days: int = Query(default=180, ge=2, le=1095),
) -> PriceHistory:
    """Daily price history by symbol, or by network and contract address."""
    try:
        return await alchemy.fetch_price_history(
            symbol=symbol, network=network, contract_address=address, days=days
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/risk/{address}", response_model=RiskMetrics)
async def get_risk(
    address: str,
    days: int = Query(default=180, ge=30, le=1095),
) -> RiskMetrics:
    """Volatility, VaR, expected shortfall, drawdown and correlation."""
    try:
        portfolio, estimate = await analysis.load_estimate(address, days=days)
        return analysis.compute_risk(portfolio, estimate)
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/prediction-markets", response_model=list[AssetPredictionMarkets])
async def get_prediction_markets(
    assets: str = Query(description="Comma-separated symbols, e.g. ETH,BTC"),
    with_change: bool = False,
) -> list[AssetPredictionMarkets]:
    """Active Polymarket markets relevant to the given assets."""
    symbols = [symbol.strip().upper() for symbol in assets.split(",") if symbol.strip()]
    if not symbols:
        raise HTTPException(status_code=400, detail="No assets supplied")

    try:
        return await polymarket.get_markets_for_assets(symbols, with_change=with_change)
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/market-stress", response_model=MarketStress)
async def get_market_stress(
    assets: str = Query(description="Comma-separated symbols, e.g. ETH,BTC"),
) -> MarketStress:
    """Liquidity-weighted downside signal derived from prediction markets."""
    symbols = [symbol.strip().upper() for symbol in assets.split(",") if symbol.strip()]

    try:
        markets = await polymarket.get_markets_for_assets(symbols)
        return polymarket.compute_market_stress(markets)
    except Exception as error:
        raise _handle(error) from error


@app.post("/api/simulate", response_model=SimulationResult)
async def run_simulation(request: SimulationRequest) -> SimulationResult:
    """Run the Monte Carlo engine over a wallet's current holdings."""
    settings = get_settings()

    if request.simulations > settings.max_simulations:
        raise HTTPException(
            status_code=400,
            detail=f"simulations exceeds the limit of {settings.max_simulations}",
        )

    try:
        _, estimate = await analysis.load_estimate(request.wallet_address)

        stress = (
            await analysis.load_market_stress(estimate)
            if request.use_prediction_markets
            else None
        )

        return analysis.run_simulation(
            estimate,
            estimate.total_value,
            horizon_days=request.horizon_days,
            simulations=request.simulations,
            seed=request.seed,
            stress=stress,
            stablecoin_ratio=request.stablecoin_ratio,
        )
    except Exception as error:
        raise _handle(error) from error


@app.post("/api/simulate/scenarios", response_model=list[ScenarioResult])
async def run_scenarios(request: SimulationRequest) -> list[ScenarioResult]:
    """Compare stablecoin ratios under one identical set of market draws."""
    try:
        _, estimate = await analysis.load_estimate(request.wallet_address)

        stress = (
            await analysis.load_market_stress(estimate)
            if request.use_prediction_markets
            else None
        )

        return analysis.run_scenarios(
            estimate,
            estimate.total_value,
            horizon_days=request.horizon_days,
            simulations=request.simulations,
            seed=request.seed,
            stress=stress,
        )
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/analysis/{address}")
async def full_analysis(
    address: str,
    horizon_days: int = Query(default=90, ge=1, le=1095),
    simulations: int = Query(default=10_000, ge=100, le=200_000),
    seed: int | None = None,
    refresh: bool = Query(default=False, description="Bypass the cached snapshot"),
) -> dict:
    """Portfolio, risk, market stress and simulation in one pass.

    This is the deterministic pipeline only. It stops short of an allocation
    decision, which is the job of the agent layer.
    """
    try:
        if refresh:
            analysis_cache.clear()

        portfolio, estimate = await analysis.load_estimate(address)
        stress = await analysis.load_market_stress(estimate)

        risk = analysis.compute_risk(portfolio, estimate)
        simulation = analysis.run_simulation(
            estimate,
            estimate.total_value,
            horizon_days=horizon_days,
            simulations=simulations,
            seed=seed,
            stress=stress,
        )
        scenarios = analysis.run_scenarios(
            estimate,
            estimate.total_value,
            horizon_days=horizon_days,
            simulations=simulations,
            seed=seed,
            stress=stress,
        )

        return {
            "portfolio": portfolio,
            "risk": risk,
            "market_stress": stress,
            "simulation": simulation,
            "scenarios": scenarios,
            "excluded_from_analysis": estimate.excluded,
        }
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/recommendation/{address}", response_model=Recommendation)
async def get_recommendation(
    address: str,
    goal: str | None = Query(
        default=None,
        description=(
            "A preset ('balanced', 'preserve capital', 'grow steadily', ...) or "
            "free text. Presets are resolved from a table with no model call. "
            "Defaults to the goal saved for this wallet, then 'balanced'."
        ),
    ),
    horizon_days: int | None = Query(default=None, ge=1, le=1095),
    explain: bool = Query(
        default=True, description="Run the judgement agent over the decision"
    ),
) -> Recommendation:
    """Run the full agent pipeline and return a recommendation.

    The allocation is computed deterministically; the judgement agent only
    explains it.
    """
    if not goal:
        saved = await database.get_goal(address)
        goal = saved["goal"] if saved else "balanced"

    try:
        return await pipeline.recommend(
            address, goal, horizon_days=horizon_days, explain=explain
        )
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/goals/presets")
async def goal_presets() -> list[dict]:
    """The predefined goals. Choosing one never calls the model."""
    return goal_layer.preset_options()


@app.get("/api/goal/{address}")
async def get_goal(address: str) -> dict:
    """The goal saved for this wallet, or a null goal."""
    return await database.get_goal(address) or {"goal": None, "updated_at": None, "persisted": False}


@app.put("/api/goal/{address}")
async def put_goal(address: str, request: GoalRequest) -> dict:
    """Save the wallet's goal. `persisted` says whether it reached the database."""
    if not ADDRESS_PATTERN.fullmatch(address):
        raise HTTPException(status_code=400, detail="Enter a valid 42-character address starting with 0x")

    goal = request.goal.strip()
    persisted = await database.save_goal(address, goal)
    return {"goal": goal, "persisted": persisted}


@app.post("/api/refresh/run")
async def run_refresh() -> dict:
    """Run the background refresh jobs now, instead of waiting for the interval."""
    return await refresh.run_once()


@app.get("/api/recommendation/{address}/history")
async def recommendation_history(address: str, limit: int = Query(default=10, ge=1, le=50)) -> list[dict]:
    """Past recommendations for this wallet. Empty without a database."""
    return await database.recent_recommendations(address, limit)


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest) -> StreamingResponse:
    """Stream an answer about the wallet as server-sent events.

    The quantitative snapshot is loaded (from cache after the first call) and
    handed to the model as context, so the assistant explains the engine's
    numbers rather than producing its own.
    """
    settings = get_settings()
    if not llm.configured():
        raise HTTPException(
            status_code=503,
            detail="The chat runs on NVIDIA NIM, which needs NVIDIA_API_KEY in backend/.env.",
        )

    try:
        portfolio, estimate = await analysis.load_estimate(request.wallet_address)
        risk = analysis.compute_risk(portfolio, estimate)
        simulation = analysis.run_simulation(
            estimate,
            estimate.total_value,
            horizon_days=settings.default_horizon_days,
            simulations=5_000,
            seed=7,
        )
    except Exception as error:
        raise _handle(error) from error

    async def events():
        try:
            stream = chat.stream_reply(
                message=request.message,
                history=[item.model_dump() for item in request.history],
                portfolio=portfolio,
                risk=risk,
                simulation=simulation,
                estimate=estimate,
                excluded=estimate.excluded,
            )
            async for event in stream:
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as error:  # a mid-stream failure still needs a frame
            logger.exception("Chat stream failed")
            payload = {"type": "error", "message": str(error)}
            yield f"data: {json.dumps(payload)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def main() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
