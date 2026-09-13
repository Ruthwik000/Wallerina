"""Amazon SQS — the simulation pipeline.

Documented role: queue computationally expensive Monte Carlo jobs so the API
does not have to wait for them.

A 50,000-path, 365-day run is slow enough that holding an HTTP request open for
it is the wrong shape. Those go on the queue; a worker consumes them and writes
the result to RDS, and the client polls for it.

Smaller interactive runs stay inline — queueing a 90-day, 5,000-path simulation
would add latency rather than remove it. ``should_queue`` draws that line in
one place.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from backend.aws.client import AwsUnavailable, client
from backend.core.config import get_settings

logger = logging.getLogger(__name__)


def should_queue(simulations: int, horizon_days: int) -> bool:
    """Whether a job is heavy enough to be worth offloading."""
    settings = get_settings()
    if not settings.sqs_queue_url:
        return False
    # Path count times horizon approximates the work done.
    return simulations * horizon_days >= settings.simulation_queue_threshold


def enqueue_simulation(
    wallet_address: str,
    *,
    horizon_days: int,
    simulations: int,
    stablecoin_ratio: float | None = None,
    seed: int | None = None,
    use_prediction_markets: bool = False,
    job_id: str | None = None,
) -> str | None:
    """Queue a simulation. Returns the job id, or None if not queued.

    Pass ``job_id`` when the job's database row already exists, so the worker
    writes its result into that row.
    """
    settings = get_settings()
    if not settings.sqs_queue_url:
        return None

    job_id = job_id or str(uuid.uuid4())
    body = {
        "job_id": job_id,
        "wallet_address": wallet_address,
        "horizon_days": horizon_days,
        "simulations": simulations,
        "stablecoin_ratio": stablecoin_ratio,
        "seed": seed,
        "use_prediction_markets": use_prediction_markets,
        "requested_at": datetime.now(UTC).isoformat(),
    }

    try:
        client("sqs").send_message(
            QueueUrl=settings.sqs_queue_url,
            MessageBody=json.dumps(body),
        )
        logger.info("Queued simulation %s for %s", job_id, wallet_address)
        return job_id
    except AwsUnavailable:
        return None
    except Exception as error:
        logger.warning("Could not queue simulation: %s", error)
        return None


# How long a received job stays hidden from other consumers. It must outlast the
# slowest simulation: if it expires mid-run, SQS hands the same job out again
# and it is computed twice. Set per receive, so it holds whatever the queue's
# own default is.
JOB_VISIBILITY_SECONDS = 900


def receive_jobs(max_messages: int = 1, wait_seconds: int = 20) -> list[dict]:
    """Long-poll for queued jobs. Used by the simulation worker."""
    settings = get_settings()
    if not settings.sqs_queue_url:
        return []

    try:
        response = client("sqs").receive_message(
            QueueUrl=settings.sqs_queue_url,
            MaxNumberOfMessages=max(1, min(max_messages, 10)),
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=JOB_VISIBILITY_SECONDS,
        )
    except (AwsUnavailable, Exception) as error:
        logger.warning("Could not read the simulation queue: %s", error)
        return []

    jobs = []
    for message in response.get("Messages", []):
        try:
            payload = json.loads(message["Body"])
            payload["_receipt_handle"] = message["ReceiptHandle"]
            jobs.append(payload)
        except json.JSONDecodeError:
            logger.warning("Discarding malformed queue message")

    return jobs


def complete_job(receipt_handle: str) -> None:
    """Delete a message once its result is durably stored."""
    settings = get_settings()
    if not settings.sqs_queue_url:
        return

    try:
        client("sqs").delete_message(
            QueueUrl=settings.sqs_queue_url, ReceiptHandle=receipt_handle
        )
    except Exception as error:
        logger.warning("Could not delete queue message: %s", error)
