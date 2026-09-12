"""Amazon S3 — historical dataset storage.

Documented role: hold the large historical market-data and Polymarket datasets
the quantitative engine reads.

Price history is the expensive part of an analysis: one request per asset,
every time. Caching each series in S3 under a content-addressed key turns a
repeat analysis into a single bulk read, and gives Lambda somewhere to write
the nightly refresh.

Falls back to the in-process cache when S3 is unavailable, so behaviour is
identical without AWS — only slower across restarts.
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import UTC, datetime

from backend.aws.client import AwsUnavailable, client
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

PRICE_PREFIX = "price-history"
SNAPSHOT_PREFIX = "portfolio-snapshots"


def _key(prefix: str, name: str, day: str | None = None) -> str:
    """Date-partitioned key, so lifecycle rules can expire old data cheaply."""
    day = day or datetime.now(UTC).strftime("%Y-%m-%d")
    return f"{prefix}/{day}/{name}.json.gz"


def put_json(key: str, payload: dict | list) -> bool:
    """Write a gzipped JSON object. Returns whether it was stored."""
    settings = get_settings()
    if not settings.s3_bucket:
        return False

    try:
        body = gzip.compress(json.dumps(payload, separators=(",", ":")).encode())
        client("s3").put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ContentEncoding="gzip",
        )
        return True
    except AwsUnavailable:
        return False
    except Exception as error:
        logger.warning("S3 write failed for %s: %s", key, error)
        return False


def get_json(key: str) -> dict | list | None:
    """Read a gzipped JSON object, or None if absent."""
    settings = get_settings()
    if not settings.s3_bucket:
        return None

    try:
        response = client("s3").get_object(Bucket=settings.s3_bucket, Key=key)
        return json.loads(gzip.decompress(response["Body"].read()))
    except AwsUnavailable:
        return None
    except Exception as error:
        # A miss is the common case and is not worth a warning.
        logger.debug("S3 read miss for %s: %s", key, error)
        return None


def cache_price_history(symbol: str, points: list[dict]) -> bool:
    return put_json(_key(PRICE_PREFIX, symbol.upper()), points)


def cached_price_history(symbol: str) -> list[dict] | None:
    payload = get_json(_key(PRICE_PREFIX, symbol.upper()))
    return payload if isinstance(payload, list) else None


def store_snapshot(address: str, snapshot: dict) -> bool:
    """Archive a portfolio snapshot for later historical analysis."""
    stamp = datetime.now(UTC).strftime("%H%M%S")
    return put_json(_key(SNAPSHOT_PREFIX, f"{address.lower()}-{stamp}"), snapshot)
