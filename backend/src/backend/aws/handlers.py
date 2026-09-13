"""AWS Lambda entry points.

Documented roles:
* Lambda — data ingestion and scheduled jobs (market data, Polymarket,
  portfolio snapshots)
* EventBridge — triggers those jobs on a schedule
* SQS — delivers queued Monte Carlo jobs to the simulation worker

Each handler is a thin adapter: it owns the event shape and the asyncio bridge,
and calls the same service code the API uses. Nothing here reimplements engine
logic, so a scheduled refresh and an interactive request cannot drift apart.

Suggested EventBridge schedules (matching the in-app refresh, services/refresh.py):
    refresh_market_data     rate(5 minutes)
    refresh_prediction_data rate(5 minutes)
    snapshot_portfolios     rate(5 minutes)

The async bodies also run inside the API process on the same interval, so the
shared HTTP client is only shut down by the call that started it.
"""

from __future__ import annotations

import asyncio
import logging

from backend.aws import database, queue, storage, telemetry
from backend.core.config import get_settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Assets whose history is worth pre-warming regardless of who is connected.
CORE_ASSETS = ["ETH", "BTC", "USDC", "USDT", "DAI", "POL", "ARB", "OP"]


_secrets_loaded = False


def _run(coroutine):
    """Run an async body inside Lambda's synchronous handler contract.

    Every invocation gets a fresh event loop, so nothing bound to the previous
    loop may outlive it: the database pool is closed before returning, or the
    next warm invocation would reuse connections from a dead loop.
    """
    global _secrets_loaded
    if not _secrets_loaded:
        # The API loads Secrets Manager in its startup hook; a Lambda has none.
        from backend.aws import secrets

        secrets.load_into_environment()
        _secrets_loaded = True

    async def invoke():
        try:
            return await coroutine
        finally:
            await database.close()

    return asyncio.run(invoke())


# --------------------------------------------------------------------------
# Scheduled: market data refresh (EventBridge -> Lambda)
# --------------------------------------------------------------------------


def refresh_market_data(event=None, context=None) -> dict:
    """Pre-warm price history for core assets into S3."""
    return _run(_refresh_market_data())


async def _refresh_market_data() -> dict:
    from backend.services import http
    from backend.services.wallet import alchemy

    started = await http.startup()
    stored, failed = 0, 0

    try:
        with telemetry.timed("MarketDataRefresh"):
            for symbol in CORE_ASSETS:
                try:
                    history = await alchemy.fetch_price_history(
                        symbol=symbol, days=get_settings().history_days
                    )
                    points = [
                        {"timestamp": p.timestamp, "value": p.value}
                        for p in history.points
                    ]
                    if points and storage.cache_price_history(symbol, points):
                        stored += 1
                except Exception as error:
                    logger.warning("Refresh failed for %s: %s", symbol, error)
                    telemetry.record_upstream_failure("alchemy")
                    failed += 1
    finally:
        if started:
            await http.shutdown()

    telemetry.put_metric("MarketDataAssetsStored", stored, "Count")
    logger.info("Market refresh: %s stored, %s failed", stored, failed)
    return {"stored": stored, "failed": failed}


# --------------------------------------------------------------------------
# Scheduled: prediction-market refresh
# --------------------------------------------------------------------------


def refresh_prediction_data(event=None, context=None) -> dict:
    return _run(_refresh_prediction_data())


async def _refresh_prediction_data() -> dict:
    from backend.services import http
    from backend.services.polymarket import client as polymarket

    started = await http.startup()

    try:
        with telemetry.timed("PredictionDataRefresh"):
            markets = await polymarket.get_markets_for_assets(
                ["BTC", "ETH", "SOL", "DOGE", "XRP"]
            )
            payload = [entry.model_dump() for entry in markets]
            total = sum(len(entry.markets) for entry in markets)

            if total:
                storage.put_json("polymarket/latest.json.gz", payload)
            else:
                telemetry.record_upstream_failure("polymarket")
    finally:
        if started:
            await http.shutdown()

    telemetry.put_metric("PredictionMarketsStored", total, "Count")
    logger.info("Prediction refresh: %s markets", total)
    return {"markets": total}


# --------------------------------------------------------------------------
# Scheduled: portfolio snapshots for tracked wallets
# --------------------------------------------------------------------------


def snapshot_portfolios(event=None, context=None) -> dict:
    """Archive a daily snapshot for every wallet the database knows about."""
    return _run(_snapshot_portfolios())


async def _snapshot_portfolios() -> dict:
    from backend.services import analysis, http

    connection_pool = await database.pool()
    if connection_pool is None:
        logger.info("No database configured; nothing to snapshot")
        return {"snapshots": 0}

    async with connection_pool.acquire() as connection:
        rows = await connection.fetch("SELECT address FROM wallets")

    started = await http.startup()
    captured = 0

    try:
        for row in rows:
            address = row["address"]
            try:
                portfolio, estimate = await analysis.load_estimate(
                    address, use_cache=False
                )
                risk = analysis.compute_risk(portfolio, estimate)
                if await database.save_snapshot(
                    address, portfolio.model_dump(), risk.model_dump()
                ):
                    captured += 1
                storage.store_snapshot(address, portfolio.model_dump(mode="json"))
            except Exception as error:
                logger.warning("Snapshot failed for %s: %s", address, error)
    finally:
        if started:
            await http.shutdown()

    telemetry.put_metric("PortfolioSnapshots", captured, "Count")
    return {"snapshots": captured, "wallets": len(rows)}


# --------------------------------------------------------------------------
# SQS-triggered: the simulation worker
# --------------------------------------------------------------------------


def run_simulation_jobs(event=None, context=None) -> dict:
    """Consume queued Monte Carlo jobs and persist their results.

    Accepts an SQS Lambda event, and falls back to polling the queue directly
    so the same function works as a standalone worker process.
    """
    return _run(_run_simulation_jobs(event))


# Failures that retrying cannot fix: the job is marked failed and its message
# deleted. Anything else (a provider timeout, a database blip) is left for SQS to
# redeliver after the visibility timeout; a redrive policy on the queue moves a
# message that keeps failing to a dead-letter queue.
PERMANENT_JOB_ERRORS = (KeyError, TypeError, ValueError)


async def _process_job(job: dict) -> str:
    """Run one queued job. Returns 'complete', 'failed' or 'retry'."""
    from backend.services import analysis

    job_id = job.get("job_id")

    try:
        with telemetry.timed("QueuedSimulation"):
            _, estimate = await analysis.load_estimate(job["wallet_address"])
            stress = (
                await analysis.load_market_stress(estimate)
                if job.get("use_prediction_markets")
                else None
            )
            # CPU-bound: kept off the event loop, which in the API process is
            # also serving requests.
            result = await asyncio.to_thread(
                analysis.run_simulation,
                estimate,
                estimate.total_value,
                horizon_days=job["horizon_days"],
                simulations=job["simulations"],
                seed=job.get("seed"),
                stress=stress,
                stablecoin_ratio=job.get("stablecoin_ratio"),
            )
    except (analysis.InsufficientDataError, *PERMANENT_JOB_ERRORS) as error:
        logger.warning("Simulation job %s failed permanently: %s", job_id, error)
        telemetry.put_metric("SimulationFailures", 1, "Count")
        if job_id:
            await database.fail_simulation_job(job_id, f"{type(error).__name__}: {error}")
        return "failed"
    except Exception:
        logger.exception("Simulation job %s failed; leaving it for redelivery", job_id)
        telemetry.put_metric("SimulationFailures", 1, "Count")
        return "retry"

    if not job_id or not await database.complete_simulation_job(job_id, result.model_dump(mode="json")):
        # The result is not durable, so the message must not be deleted.
        return "retry"
    return "complete"


async def _run_simulation_jobs(event, wait_seconds: int = 20) -> dict:
    from backend.services import http

    records = (event or {}).get("Records") if isinstance(event, dict) else None

    if records:
        import json

        jobs = []
        for record in records:
            try:
                job = json.loads(record["body"])
            except (KeyError, json.JSONDecodeError):
                logger.warning("Discarding malformed SQS record")
                continue
            job["_message_id"] = record.get("messageId")
            jobs.append(job)
    else:
        # A long poll blocks for up to wait_seconds, so it runs in a thread.
        jobs = await asyncio.to_thread(queue.receive_jobs, 5, wait_seconds)

    summary = {"processed": 0, "failed": 0, "retried": 0, "batchItemFailures": []}
    if not jobs:
        return summary

    started = await http.startup()

    try:
        for job in jobs:
            outcome = await _process_job(job)

            if outcome == "retry":
                summary["retried"] += 1
                # Reported back to a Lambda event source configured with
                # ReportBatchItemFailures, so only these messages are retried.
                if job.get("_message_id"):
                    summary["batchItemFailures"].append({"itemIdentifier": job["_message_id"]})
                continue

            summary["processed" if outcome == "complete" else "failed"] += 1
            if handle := job.get("_receipt_handle"):
                await asyncio.to_thread(queue.complete_job, handle)
    finally:
        if started:
            await http.shutdown()

    return summary
