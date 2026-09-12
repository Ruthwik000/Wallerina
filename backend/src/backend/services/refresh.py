"""Periodic data refresh — the every-15-minutes job.

Runs inside the API process. Every REFRESH_INTERVAL_MINUTES (default 15) it:

* re-caches price history for the core assets in S3,
* refreshes Polymarket data into S3, and
* snapshots every wallet the database tracks (portfolio and risk metrics).

The same three jobs exist as Lambda handlers in ``aws/handlers.py`` for an
EventBridge ``rate(15 minutes)`` schedule. When they run there, set
REFRESH_ENABLED=false so the work is not done twice.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from backend.aws import handlers
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Leaves startup and the first page load the network before the first run.
INITIAL_DELAY_SECONDS = 60.0

# Resolved by name at run time so each job can be swapped out in tests.
JOBS = {
    "market_data": "_refresh_market_data",
    "prediction_markets": "_refresh_prediction_data",
    "snapshots": "_snapshot_portfolios",
}

status: dict = {
    "enabled": False,
    "interval_minutes": None,
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def run_once() -> dict:
    """Run every refresh job once. One failing job does not stop the others."""
    settings = get_settings()
    status.update(running=True, last_started_at=_now())
    results: dict = {}

    try:
        for name, attribute in JOBS.items():
            if name == "snapshots" and not settings.refresh_snapshots:
                continue
            try:
                results[name] = await getattr(handlers, attribute)()
            except Exception as error:
                logger.exception("Refresh job %s failed", name)
                results[name] = {"error": str(error)}
    finally:
        status.update(running=False, last_finished_at=_now(), last_result=results)

    logger.info("Background refresh finished: %s", results)
    return results


async def _loop(interval_seconds: float, initial_delay: float) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        await run_once()
        await asyncio.sleep(interval_seconds)


def start(initial_delay: float = INITIAL_DELAY_SECONDS) -> asyncio.Task | None:
    """Start the refresh loop, or return None when it is disabled."""
    settings = get_settings()
    status.update(enabled=settings.refresh_enabled, interval_minutes=settings.refresh_interval_minutes)

    if not settings.refresh_enabled:
        logger.info("Background refresh disabled")
        return None

    logger.info("Background refresh every %s minutes", settings.refresh_interval_minutes)
    return asyncio.create_task(
        _loop(settings.refresh_interval_minutes * 60, initial_delay), name="wallerina-refresh"
    )


async def stop(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
