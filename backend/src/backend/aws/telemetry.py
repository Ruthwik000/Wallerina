"""Amazon CloudWatch — metrics and logging.

Documented role: collect backend logs, Lambda errors, simulation failures, API
latency and infrastructure metrics.

Logs reach CloudWatch for free under ECS and Lambda through stdout, so this
module only handles custom metrics — the numbers that matter operationally and
that no log line gives you: analysis latency, simulation duration, upstream
failures, and how often the engine recommends a rebalance.

Metrics are best-effort. A telemetry failure must never surface to a user, so
every call here swallows its errors.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from backend.aws.client import AwsUnavailable, client
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

NAMESPACE = "Wallerina"


def put_metric(
    name: str, value: float, unit: str = "None", **dimensions: str
) -> None:
    """Record one datapoint. Silent on failure."""
    settings = get_settings()
    if not settings.cloudwatch_enabled:
        return

    try:
        client("cloudwatch").put_metric_data(
            Namespace=NAMESPACE,
            MetricData=[
                {
                    "MetricName": name,
                    "Value": float(value),
                    "Unit": unit,
                    "Dimensions": [
                        {"Name": key, "Value": str(val)}
                        for key, val in dimensions.items()
                    ],
                }
            ],
        )
    except AwsUnavailable:
        pass
    except Exception as error:
        logger.debug("CloudWatch metric %s dropped: %s", name, error)


@contextmanager
def timed(name: str, **dimensions: str):
    """Time a block and publish it as a millisecond metric.

    Emits on the failure path too, so a slow error is still visible.
    """
    started = time.perf_counter()
    failed = False
    try:
        yield
    except Exception:
        failed = True
        raise
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        put_metric(name, elapsed_ms, "Milliseconds", **dimensions)
        if failed:
            put_metric(f"{name}Failures", 1, "Count", **dimensions)


def record_upstream_failure(provider: str) -> None:
    put_metric("UpstreamFailure", 1, "Count", Provider=provider)


def record_recommendation(rebalance_required: bool, confidence: float) -> None:
    put_metric("RecommendationConfidence", confidence, "None")
    put_metric(
        "RebalanceRecommended", 1 if rebalance_required else 0, "Count"
    )
