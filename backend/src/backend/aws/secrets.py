"""AWS Secrets Manager.

Documented role: hold the Alchemy, market-data, database and model credentials
instead of exposing them in application code.

At startup the application asks for one secret containing a JSON object of
key/value pairs. Anything it returns is layered *under* the process
environment, so a locally exported variable still wins — which keeps local
development working unchanged.
"""

from __future__ import annotations

import json
import logging
import os

from backend.aws.client import AwsUnavailable, client
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Keys the application understands. Anything else in the secret is ignored.
KNOWN_KEYS = {
    "ALCHEMY_API_KEY",
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
    "POLYMARKET_GAMMA_URL",
    "POLYMARKET_CLOB_URL",
}


def load_into_environment() -> list[str]:
    """Fetch the configured secret and export its keys.

    Returns the names loaded. Never raises: a missing secret must not stop the
    service from starting, because the same image runs locally without AWS.
    """
    settings = get_settings()
    if not settings.aws_secret_id:
        return []

    try:
        response = client("secretsmanager").get_secret_value(
            SecretId=settings.aws_secret_id
        )
    except AwsUnavailable as error:
        logger.info("Secrets Manager not configured (%s)", error)
        return []
    except Exception as error:
        logger.warning("Could not read secret %s: %s", settings.aws_secret_id, error)
        return []

    raw = response.get("SecretString")
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Secret %s is not JSON", settings.aws_secret_id)
        return []

    loaded: list[str] = []
    for key, value in payload.items():
        if key not in KNOWN_KEYS or value in (None, ""):
            continue
        # An explicitly exported variable wins over the stored secret.
        if os.environ.get(key):
            continue
        os.environ[key] = str(value)
        loaded.append(key)

    if loaded:
        # Settings are cached, so they must be rebuilt to see the new values.
        get_settings.cache_clear()
        logger.info("Loaded %s from Secrets Manager", ", ".join(loaded))

    return loaded
