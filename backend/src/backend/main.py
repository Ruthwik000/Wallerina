"""Wallerina FastAPI application.

Scope: data retrieval and the quantitative engine only. The goal/intent layer,
the analysis agents and the allocation decision described in the specification
are not implemented yet, and no endpoint here produces a recommendation.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import get_settings
from backend.models.market import AssetPredictionMarkets, MarketStress, PriceHistory
from backend.models.portfolio import Portfolio
from backend.models.quant import (
    RiskMetrics,
    ScenarioResult,
    SimulationRequest,
    SimulationResult,
)
from backend.services import analysis, http
from backend.services.http import UpstreamError
from backend.services.polymarket import client as polymarket
from backend.services.wallet import alchemy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await http.startup()
    try:
        yield
    finally:
        await http.shutdown()


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
    if isinstance(error, UpstreamError):
        return HTTPException(status_code=502, detail=str(error))
    return HTTPException(status_code=500, detail=str(error))


@app.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "alchemy_configured": settings.alchemy_configured,
        "networks": settings.alchemy_networks,
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
) -> dict:
    """Portfolio, risk, market stress and simulation in one pass.

    This is the deterministic pipeline only. It stops short of an allocation
    decision, which is the job of the agent layer.
    """
    try:
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


def main() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
