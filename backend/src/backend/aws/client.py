"""AWS client factory and availability gate.

Every AWS integration in this package is **optional**. The application runs
fully without any of it — S3 caching, SQS offloading, RDS persistence and
CloudWatch metrics each degrade to a local or no-op path. That keeps local
development and the demo path working with no AWS account at all, and matches
the documented role of AWS here: infrastructure around the engine, not a
dependency of it.

Credentials resolve through the standard boto3 chain (environment, shared
config, or the ECS task role), so nothing needs to be hardcoded.
"""

from __future__ import annotations

import functools
import logging

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    BOTO_AVAILABLE = True
except ImportError:  # pragma: no cover - boto3 is a declared dependency
    BOTO_AVAILABLE = False
    BotoCoreError = ClientError = Exception  # type: ignore[assignment, misc]


class AwsUnavailable(RuntimeError):
    """AWS is not configured, or the call failed."""


@functools.lru_cache(maxsize=8)
def client(service: str):
    """A cached boto3 client for one service.

    Cached because client construction parses botocore's service model, which
    is slow enough to matter on a per-request path.
    """
    if not BOTO_AVAILABLE:
        raise AwsUnavailable("boto3 is not installed")

    settings = get_settings()
    if not settings.aws_enabled:
        raise AwsUnavailable("AWS_ENABLED is false")

    kwargs: dict = {"region_name": settings.aws_region}

    # Explicit keys are only used when supplied; otherwise boto3 resolves the
    # task role, which is what runs in ECS.
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token

    if settings.aws_endpoint_url:
        # Lets the whole stack point at LocalStack or MinIO for local testing.
        kwargs["endpoint_url"] = settings.aws_endpoint_url

    return boto3.client(service, **kwargs)


def available(service: str) -> bool:
    """Whether calls to this service can be attempted at all."""
    try:
        client(service)
        return True
    except Exception:
        return False
