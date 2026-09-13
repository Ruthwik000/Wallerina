"""In-process simulation worker.

Queued Monte Carlo jobs are consumed by ``aws/handlers.run_simulation_jobs``.
Deployed, that runs as a Lambda on the queue's event source, or as its own ECS
service. Locally there is neither, so the API process runs the same handler in
a loop: long-poll the queue, run what arrives, repeat. Set
SIMULATION_WORKER_ENABLED=false wherever a separate consumer exists, or the two
will compete for messages.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime

from backend.aws import handlers
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Short enough that shutdown is not held up waiting for a poll to return.
POLL_WAIT_SECONDS = 10
# A poll that returns at once found no queue to wait on (AWS disabled, bad
# credentials); back off instead of spinning.
IDLE_BACKOFF_SECONDS = 30.0

status: dict = {
    "enabled": False,
    "processed": 0,
    "failed": 0,
    "retried": 0,
    "last_poll_at": None,
    "last_error": None,
}


async def poll_once() -> dict:
    summary = await handlers._run_simulation_jobs(None, wait_seconds=POLL_WAIT_SECONDS)
    for key in ("processed", "failed", "retried"):
        status[key] += summary[key]
    status["last_poll_at"] = datetime.now(UTC).isoformat()
    return summary


async def _loop() -> None:
    while True:
        started = time.monotonic()
        try:
            summary = await poll_once()
            busy = summary["processed"] or summary["failed"] or summary["retried"]
        except Exception as error:
            logger.exception("Simulation worker poll failed")
            status["last_error"] = str(error)
            busy = False

        if not busy and time.monotonic() - started < 1.0:
            await asyncio.sleep(IDLE_BACKOFF_SECONDS)


def start() -> asyncio.Task | None:
    """Start the worker loop, or return None when there is no queue to consume."""
    settings = get_settings()
    enabled = bool(settings.sqs_queue_url and settings.simulation_worker_enabled)
    status["enabled"] = enabled

    if not enabled:
        logger.info("In-process simulation worker disabled")
        return None

    logger.info("In-process simulation worker consuming %s", settings.sqs_queue_url)
    return asyncio.create_task(_loop(), name="wallerina-simulation-worker")


async def stop(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
