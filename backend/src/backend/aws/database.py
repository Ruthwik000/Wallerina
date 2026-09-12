"""Amazon RDS (PostgreSQL) — the application database.

Documented role: store users, wallets, portfolio snapshots, market data, risk
metrics, simulations and recommendations.

This also satisfies the backend specification's requirement to log every
recommendation with the inputs that produced it — a recommendation that cannot
be reconstructed later cannot be audited.

Connection is lazy and entirely optional: with no RDS_HOST the application
runs exactly as before, minus persistence.

Authentication is AWS IAM, never a password. Aurora IAM tokens expire after 15
minutes, so a token is not generated once and reused: the pool's ``connect``
hook generates a fresh one immediately before each new physical connection.
Connections already open stay valid past the token's expiry, because the token
is only checked when a connection authenticates.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from datetime import UTC, datetime
from typing import Any

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:  # pragma: no cover
    ASYNCPG_AVAILABLE = False

import boto3

_pool: Any = None
# Why the last pool creation failed, for the database health check.
_last_error: str | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    address           TEXT PRIMARY KEY,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_analysed_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    address           TEXT NOT NULL REFERENCES wallets(address) ON DELETE CASCADE,
    captured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_value_usd   NUMERIC(24, 2) NOT NULL,
    stablecoin_ratio  REAL NOT NULL,
    concentration     REAL NOT NULL,
    holdings          JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS portfolio_snapshots_address_time
    ON portfolio_snapshots (address, captured_at DESC);

CREATE TABLE IF NOT EXISTS risk_metrics (
    id                BIGSERIAL PRIMARY KEY,
    address           TEXT NOT NULL REFERENCES wallets(address) ON DELETE CASCADE,
    captured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    annual_volatility REAL NOT NULL,
    value_at_risk     REAL NOT NULL,
    max_drawdown      REAL NOT NULL,
    metrics           JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS risk_metrics_address_time
    ON risk_metrics (address, captured_at DESC);

CREATE TABLE IF NOT EXISTS simulations (
    job_id            TEXT PRIMARY KEY,
    address           TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued',
    requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ,
    parameters        JSONB NOT NULL,
    result            JSONB
);
CREATE INDEX IF NOT EXISTS simulations_address ON simulations (address, requested_at DESC);

-- Every recommendation is stored with the inputs behind it, so any past
-- decision can be reconstructed exactly.
CREATE TABLE IF NOT EXISTS recommendations (
    id                BIGSERIAL PRIMARY KEY,
    address           TEXT NOT NULL REFERENCES wallets(address) ON DELETE CASCADE,
    generated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    goal              TEXT,
    target_ratio      REAL NOT NULL,
    current_ratio     REAL NOT NULL,
    rebalance         BOOLEAN NOT NULL,
    confidence        REAL NOT NULL,
    payload           JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS recommendations_address_time
    ON recommendations (address, generated_at DESC);

-- The goal each wallet is analysed against, so it survives reloads and devices.
CREATE TABLE IF NOT EXISTS wallet_goals (
    address           TEXT PRIMARY KEY REFERENCES wallets(address) ON DELETE CASCADE,
    goal              TEXT NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Goals are also kept in memory, so a chosen goal still works for this process
# when no database is configured.
_memory_goals: dict[str, dict] = {}


@functools.lru_cache(maxsize=1)
def _rds_client():
    """The boto3 RDS client used to sign IAM tokens.

    Deliberately built from the default credential chain (environment, shared
    ~/.aws config, or the ECS task role in production), not from the AWS_* key
    settings. The chain's credentials refresh themselves, so a long-running
    task keeps signing valid tokens when its role credentials rotate.
    """
    settings = get_settings()
    session = boto3.Session(profile_name=settings.aws_profile or None)
    return session.client("rds", region_name=settings.aws_region)


def generate_auth_token() -> str:
    """A fresh IAM authentication token for the configured database user.

    Signed locally with the current AWS credentials; valid for 15 minutes.
    Never log the return value: it is a password.
    """
    settings = get_settings()
    return _rds_client().generate_db_auth_token(
        DBHostname=settings.rds_host,
        Port=settings.rds_port,
        DBUsername=settings.rds_user,
    )


async def _iam_connect(*args, **kwargs):
    """The pool's connect hook: runs for every new physical connection.

    The token is generated here, immediately before connecting, so it is never
    older than a few milliseconds when Aurora checks it. Signing may read
    credentials from the ECS metadata endpoint, so it runs off the event loop.
    """
    kwargs["password"] = await asyncio.to_thread(generate_auth_token)
    return await asyncpg.connect(*args, **kwargs)


async def pool():
    """Lazily create the connection pool, or return None if unconfigured."""
    global _pool, _last_error
    settings = get_settings()

    if not settings.database_configured or not ASYNCPG_AVAILABLE:
        return None

    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                host=settings.rds_host,
                port=settings.rds_port,
                database=settings.rds_database,
                user=settings.rds_user,
                ssl="require",
                min_size=1,
                max_size=settings.database_pool_size,
                command_timeout=15,
                # Idle connections are closed after five minutes; the next one
                # opened goes through _iam_connect and gets a new token.
                max_inactive_connection_lifetime=300.0,
                connect=_iam_connect,
            )
            _last_error = None
            logger.info(
                "Connected to PostgreSQL at %s as %s (IAM auth)",
                settings.rds_host,
                settings.rds_user,
            )
        except Exception as error:
            _last_error = f"{type(error).__name__}: {error}"
            logger.warning("Database unavailable: %s", _last_error)
            return None

    return _pool


async def check() -> dict:
    """Connect and ask the database who we are: the connectivity health check."""
    settings = get_settings()
    result: dict = {
        "configured": settings.database_configured,
        "auth": "iam",
        "host": settings.rds_host or None,
        "connected": False,
    }

    connection_pool = await pool()
    if connection_pool is None:
        result["error"] = (
            _last_error
            if settings.database_configured
            else "RDS_HOST, RDS_DATABASE and RDS_USER are not all set"
        )
        return result

    try:
        async with connection_pool.acquire() as connection:
            row = await connection.fetchrow("SELECT current_user, current_database()")
        result.update(
            connected=True,
            current_user=row["current_user"],
            current_database=row["current_database"],
        )
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"

    return result


async def migrate() -> bool:
    """Create tables if they do not exist. Safe to run on every boot."""
    connection_pool = await pool()
    if connection_pool is None:
        return False

    try:
        async with connection_pool.acquire() as connection:
            await connection.execute(SCHEMA)
        logger.info("Database schema is up to date")
        return True
    except Exception as error:
        logger.warning("Migration failed: %s", error)
        return False


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def _ensure_wallet(connection, address: str) -> None:
    await connection.execute(
        """
        INSERT INTO wallets (address, last_analysed_at)
        VALUES ($1, now())
        ON CONFLICT (address) DO UPDATE SET last_analysed_at = now()
        """,
        address.lower(),
    )


async def save_snapshot(address: str, portfolio: dict, risk: dict | None) -> bool:
    """Persist a portfolio snapshot and its risk metrics."""
    connection_pool = await pool()
    if connection_pool is None:
        return False

    try:
        async with connection_pool.acquire() as connection, connection.transaction():
            await _ensure_wallet(connection, address)

            await connection.execute(
                """
                INSERT INTO portfolio_snapshots
                    (address, total_value_usd, stablecoin_ratio, concentration, holdings)
                VALUES ($1, $2, $3, $4, $5)
                """,
                address.lower(),
                portfolio["total_value_usd"],
                portfolio["stablecoin_ratio"],
                portfolio["concentration"],
                json.dumps(portfolio.get("holdings", [])),
            )

            if risk:
                await connection.execute(
                    """
                    INSERT INTO risk_metrics
                        (address, annual_volatility, value_at_risk, max_drawdown, metrics)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    address.lower(),
                    risk["portfolio_annual_volatility"],
                    risk["value_at_risk"],
                    risk["max_drawdown"],
                    json.dumps(risk),
                )
        return True
    except Exception as error:
        logger.warning("Could not save snapshot for %s: %s", address, error)
        return False


async def save_recommendation(address: str, recommendation: dict) -> bool:
    """Log a recommendation with the full inputs that produced it."""
    connection_pool = await pool()
    if connection_pool is None:
        return False

    decision = recommendation["decision"]

    try:
        async with connection_pool.acquire() as connection, connection.transaction():
            await _ensure_wallet(connection, address)
            await connection.execute(
                """
                INSERT INTO recommendations
                    (address, goal, target_ratio, current_ratio, rebalance,
                     confidence, payload)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                address.lower(),
                recommendation.get("intent", {}).get("goal_type"),
                decision["target_stablecoin_ratio"],
                decision["current_stablecoin_ratio"],
                decision["rebalance_required"],
                decision["confidence"],
                json.dumps(recommendation, default=str),
            )
        return True
    except Exception as error:
        logger.warning("Could not log recommendation for %s: %s", address, error)
        return False


async def save_goal(address: str, goal: str) -> bool:
    """Store the wallet's goal. Returns whether it reached the database."""
    key = address.lower()
    _memory_goals[key] = {"goal": goal, "updated_at": datetime.now(UTC).isoformat()}

    connection_pool = await pool()
    if connection_pool is None:
        return False

    try:
        async with connection_pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO wallets (address) VALUES ($1) ON CONFLICT (address) DO NOTHING",
                key,
            )
            await connection.execute(
                """
                INSERT INTO wallet_goals (address, goal, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (address) DO UPDATE
                SET goal = EXCLUDED.goal, updated_at = now()
                """,
                key,
                goal,
            )
        return True
    except Exception as error:
        logger.warning("Could not save goal for %s: %s", address, error)
        return False


async def get_goal(address: str) -> dict | None:
    """The saved goal for a wallet: database first, then this process's memory."""
    key = address.lower()
    connection_pool = await pool()

    if connection_pool is not None:
        try:
            async with connection_pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT goal, updated_at FROM wallet_goals WHERE address = $1", key
                )
            if row:
                return {"goal": row["goal"], "updated_at": row["updated_at"].isoformat(), "persisted": True}
        except Exception as error:
            logger.warning("Could not read goal for %s: %s", address, error)

    record = _memory_goals.get(key)
    return {**record, "persisted": False} if record else None


async def recent_recommendations(address: str, limit: int = 10) -> list[dict]:
    connection_pool = await pool()
    if connection_pool is None:
        return []

    try:
        async with connection_pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT generated_at, goal, target_ratio, current_ratio,
                       rebalance, confidence
                FROM recommendations
                WHERE address = $1
                ORDER BY generated_at DESC
                LIMIT $2
                """,
                address.lower(),
                limit,
            )
        return [dict(row) for row in rows]
    except Exception as error:
        logger.warning("Could not read recommendations: %s", error)
        return []


async def record_simulation_job(job_id: str, address: str, parameters: dict) -> bool:
    connection_pool = await pool()
    if connection_pool is None:
        return False

    try:
        async with connection_pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO simulations (job_id, address, parameters)
                VALUES ($1, $2, $3)
                ON CONFLICT (job_id) DO NOTHING
                """,
                job_id,
                address.lower(),
                json.dumps(parameters),
            )
        return True
    except Exception as error:
        logger.warning("Could not record simulation job: %s", error)
        return False


async def complete_simulation_job(job_id: str, result: dict) -> bool:
    connection_pool = await pool()
    if connection_pool is None:
        return False

    try:
        async with connection_pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE simulations
                SET status = 'complete', completed_at = now(), result = $2
                WHERE job_id = $1
                """,
                job_id,
                json.dumps(result, default=str),
            )
        return True
    except Exception as error:
        logger.warning("Could not complete simulation job: %s", error)
        return False


async def simulation_job(job_id: str) -> dict | None:
    connection_pool = await pool()
    if connection_pool is None:
        return None

    try:
        async with connection_pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM simulations WHERE job_id = $1", job_id
            )
        return dict(row) if row else None
    except Exception as error:
        logger.warning("Could not read simulation job: %s", error)
        return None
