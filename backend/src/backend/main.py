"""Wallerina FastAPI application.

Data retrieval, the quantitative engine, and the agent pipeline
(``/api/recommendation``): the goal agent builds a shared context, the wallet,
market and stablecoin agents analyse under it, the allocation engine decides,
and the judgement and grounding agents explain and verify.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import re
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from backend.core import ratelimit
from backend.core.config import get_settings, production_problems
from backend.agents import goal as goal_layer
from backend.agents import llm, pipeline
from backend.aws import database, queue, secrets
from backend.assets.registry import CHAIN_IDS
from backend.models.agents import Recommendation
from backend.models.auth import NonceResponse, Session, SignInRequest
from backend.models.execution import (
    ExecutionLeg,
    ExecutionPlan,
    ExecutionRecordRequest,
    ExecutionStatus,
    LegQuote,
    PlanRequest,
)
from backend.models.chat import ChatRequest
from backend.models.preferences import GoalRequest
from backend.models.history import PerformanceHistory, RiskHistory
from backend.models.market import AssetPredictionMarkets, MarketStress, PriceHistory
from backend.models.portfolio import Portfolio
from backend.models.quant import (
    RiskMetrics,
    ScenarioResult,
    SimulationJob,
    SimulationRequest,
    SimulationResult,
)
from backend.services import analysis, auth, chat, execution, history, http, refresh, swap, worker
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

    settings = get_settings()
    if settings.is_production and (problems := production_problems(settings)):
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))

    await http.startup()
    await database.migrate()
    refresher = refresh.start()
    simulation_worker = worker.start()
    try:
        yield
    finally:
        await worker.stop(simulation_worker)
        await refresh.stop(refresher)
        await http.shutdown()
        await database.close()


app = FastAPI(
    title="Wallerina",
    description="Portfolio risk analysis and Monte Carlo simulation.",
    version="0.1.0",
    lifespan=lifespan,
)

limiter = ratelimit.SlidingWindowLimiter()


# Registered before CORS so that CORS is the outermost layer: a 429 still carries
# the headers a browser needs in order to read it.
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    settings = get_settings()
    if settings.rate_limit_per_minute > 0 and ratelimit.is_limited(request.method, request.url.path):
        key = ratelimit.client_key(request, settings.trust_proxy_headers)
        retry_after = limiter.check(key, settings.rate_limit_per_minute)
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests from this address; try again shortly."},
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_wallet(address: str, authorization: str | None) -> str:
    """The signed-in wallet, which must be ``address``."""
    token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None
    owner = auth.read_session(token) if token else None
    if owner is None:
        raise HTTPException(
            status_code=401, detail="Sign in with this wallet first", headers={"WWW-Authenticate": "Bearer"}
        )
    if owner != address.lower():
        raise HTTPException(status_code=403, detail="Signed in as a different wallet")
    return owner


def _require_admin(token: str | None) -> None:
    """Gate operational endpoints behind ADMIN_TOKEN."""
    settings = get_settings()
    if settings.admin_token:
        if not token or not hmac.compare_digest(token, settings.admin_token):
            raise HTTPException(status_code=401, detail="A valid X-Admin-Token header is required")
    elif settings.is_production:
        raise HTTPException(
            status_code=403, detail="Operational endpoints are disabled; set ADMIN_TOKEN to enable them"
        )


def _handle(error: Exception) -> HTTPException:
    """Map internal failures onto meaningful HTTP responses."""
    if isinstance(error, swap.SwapUnavailable):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(error, execution.QuoteRejected):
        return HTTPException(status_code=422, detail=str(error))
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
        "simulation_worker": worker.status,
    }


@app.get("/health/database")
async def database_health() -> dict:
    """Connect to RDS with IAM auth and run SELECT current_user, current_database()."""
    return await database.check()


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


async def _queue_simulation(request: SimulationRequest) -> SimulationJob | None:
    """Offload a heavy run to SQS. None means run it inline.

    The job row is written before the message is sent, because the worker
    stores its result in that row: without the database a queued result would
    be lost, so without the database nothing is queued.
    """
    if not queue.should_queue(request.simulations, request.horizon_days):
        return None

    job_id = str(uuid.uuid4())
    parameters = request.model_dump(mode="json")
    if not await database.record_simulation_job(job_id, request.wallet_address, parameters):
        return None

    queued = await asyncio.to_thread(
        queue.enqueue_simulation,
        request.wallet_address,
        horizon_days=request.horizon_days,
        simulations=request.simulations,
        stablecoin_ratio=request.stablecoin_ratio,
        seed=request.seed,
        use_prediction_markets=request.use_prediction_markets,
        job_id=job_id,
    )
    if queued is None:
        await database.fail_simulation_job(job_id, "Could not be queued; the simulation ran inline instead")
        return None

    return SimulationJob(
        job_id=job_id,
        status="queued",
        status_url=f"/api/simulate/jobs/{job_id}",
        parameters=parameters,
    )


@app.post(
    "/api/simulate",
    response_model=SimulationResult,
    responses={202: {"model": SimulationJob, "description": "Queued; poll status_url for the result"}},
)
async def run_simulation(request: SimulationRequest):
    """Run the Monte Carlo engine over a wallet's current holdings.

    Runs above SIMULATION_QUEUE_THRESHOLD (paths x horizon days) are queued
    instead and answered with 202 and a job to poll.
    """
    settings = get_settings()

    if request.simulations > settings.max_simulations:
        raise HTTPException(
            status_code=400,
            detail=f"simulations exceeds the limit of {settings.max_simulations}",
        )

    job = await _queue_simulation(request)
    if job is not None:
        return JSONResponse(status_code=202, content=job.model_dump(mode="json"))

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


@app.get("/api/simulate/jobs/{job_id}", response_model=SimulationJob)
async def simulation_job_status(job_id: str) -> SimulationJob:
    """State of a queued simulation, with its result once complete."""
    if not get_settings().database_configured:
        raise HTTPException(status_code=503, detail="Queued simulations need the database")

    job = await database.simulation_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No simulation job with that id")

    return SimulationJob(
        job_id=job["job_id"],
        status=job["status"],
        status_url=f"/api/simulate/jobs/{job_id}",
        requested_at=job["requested_at"],
        completed_at=job["completed_at"],
        parameters=job["parameters"],
        result=job["result"],
        error=job["error"],
    )


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
async def put_goal(
    address: str, request: GoalRequest, authorization: str | None = Header(default=None)
) -> dict:
    """Save the wallet's goal. Needs a signed-in session for that wallet.

    `persisted` says whether it reached the database.
    """
    if not ADDRESS_PATTERN.fullmatch(address):
        raise HTTPException(status_code=400, detail="Enter a valid 42-character address starting with 0x")
    _require_wallet(address, authorization)

    goal = request.goal.strip()
    persisted = await database.save_goal(address, goal)
    return {"goal": goal, "persisted": persisted}


@app.post("/api/refresh/run")
async def run_refresh(x_admin_token: str | None = Header(default=None)) -> dict:
    """Run the background refresh jobs now, instead of waiting for the interval."""
    _require_admin(x_admin_token)
    return await refresh.run_once()


@app.get("/api/recommendation/{address}/history")
async def recommendation_history(address: str, limit: int = Query(default=10, ge=1, le=50)) -> list[dict]:
    """Past recommendations for this wallet. Empty without a database."""
    return await database.recent_recommendations(address, limit)


@app.get("/api/history/{address}/performance", response_model=PerformanceHistory)
async def performance_history(
    address: str,
    recorded_days: int = Query(default=30, ge=1, le=365, description="Window for saved snapshots"),
) -> PerformanceHistory:
    """Portfolio value over time: backfilled from price history, and as recorded."""
    try:
        _, estimate = await analysis.load_estimate(address)
        recorded = await database.portfolio_value_history(address, recorded_days)
        return history.performance(estimate, recorded)
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/history/{address}/risk", response_model=RiskHistory)
async def risk_history(
    address: str,
    recorded_days: int = Query(default=30, ge=1, le=365, description="Window for saved risk metrics"),
) -> RiskHistory:
    """Rolling volatility and drawdown of today's holdings, and recorded risk metrics."""
    try:
        _, estimate = await analysis.load_estimate(address)
        recorded = await database.risk_metrics_history(address, recorded_days)
        return history.risk_history(estimate, recorded)
    except Exception as error:
        raise _handle(error) from error


@app.get("/api/auth/nonce", response_model=NonceResponse)
async def auth_nonce() -> NonceResponse:
    """A single-use nonce for a sign-in message. Valid for ten minutes."""
    nonce, expires_at = await auth.issue_nonce()
    return NonceResponse(nonce=nonce, expires_at=expires_at.isoformat())


@app.post("/api/auth/verify", response_model=Session)
async def auth_verify(request: SignInRequest) -> Session:
    """Check a signed EIP-4361 message and start a session for its wallet."""
    try:
        return await auth.verify_sign_in(request.message, request.signature)
    except auth.AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@app.post("/api/execution/{address}/plan", response_model=ExecutionPlan)
async def execution_plan(
    address: str, request: PlanRequest, authorization: str | None = Header(default=None)
) -> ExecutionPlan:
    """Turn a fresh recommendation into same-network swaps for the wallet to sign."""
    if not ADDRESS_PATTERN.fullmatch(address):
        raise HTTPException(status_code=400, detail="Enter a valid 42-character address starting with 0x")
    _require_wallet(address, authorization)

    goal = request.goal
    if not goal:
        saved = await database.get_goal(address)
        goal = saved["goal"] if saved else "balanced"

    try:
        # A fresh run, so trades reflect balances now rather than when the page loaded.
        recommendation = await pipeline.recommend(address, goal, explain=False)
        portfolio, _ = await analysis.load_estimate(address)
    except Exception as error:
        raise _handle(error) from error

    legs, skipped = execution.build_legs(portfolio.holdings, recommendation.trades)
    settings = get_settings()
    decision = recommendation.decision

    return ExecutionPlan(
        address=address,
        generated_at=datetime.now(UTC).isoformat(),
        goal=goal,
        target_stablecoin_ratio=decision.target_stablecoin_ratio,
        current_stablecoin_ratio=decision.current_stablecoin_ratio,
        rebalance_required=decision.rebalance_required,
        legs=legs,
        skipped=skipped,
        slippage_bps=settings.swap_slippage_bps,
        swaps_configured=bool(settings.zeroex_api_key),
    )


@app.post("/api/execution/{address}/quote", response_model=LegQuote)
async def execution_quote(
    address: str, leg: ExecutionLeg, authorization: str | None = Header(default=None)
) -> LegQuote:
    """A fresh 0x quote for one swap, as the transactions to sign in order."""
    if not ADDRESS_PATTERN.fullmatch(address):
        raise HTTPException(status_code=400, detail="Enter a valid 42-character address starting with 0x")
    _require_wallet(address, authorization)

    try:
        return await execution.quote_leg(leg, taker=address)
    except Exception as error:
        raise _handle(error) from error


@app.post("/api/execution/{address}/transactions", response_model=ExecutionStatus)
async def record_execution(
    address: str, request: ExecutionRecordRequest, authorization: str | None = Header(default=None)
) -> ExecutionStatus:
    """Record a transaction the wallet signed, before its outcome is known."""
    _require_wallet(address, authorization)
    persisted = await database.record_execution(
        address, request.tx_hash, request.chain_id, request.leg_id, request.kind
    )
    return ExecutionStatus(
        tx_hash=request.tx_hash, chain_id=request.chain_id, status="submitted", persisted=persisted
    )


@app.get("/api/execution/{address}/transactions/{tx_hash}", response_model=ExecutionStatus)
async def execution_transaction_status(
    address: str,
    tx_hash: str,
    chain_id: int = Query(description="Chain the transaction was sent on"),
    authorization: str | None = Header(default=None),
) -> ExecutionStatus:
    """A transaction's outcome, read from the chain rather than taken from the client."""
    _require_wallet(address, authorization)
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash):
        raise HTTPException(status_code=400, detail="Not a transaction hash")
    if chain_id not in CHAIN_IDS.values():
        raise HTTPException(status_code=400, detail="Unsupported chain")

    try:
        status = await alchemy.transaction_status(chain_id, tx_hash)
    except Exception as error:
        raise _handle(error) from error

    persisted = await database.set_execution_status(tx_hash, status) if status != "submitted" else False
    return ExecutionStatus(tx_hash=tx_hash, chain_id=chain_id, status=status, persisted=persisted)


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

    # Auto-reload watches the source tree: a development convenience only.
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=not get_settings().is_production)
