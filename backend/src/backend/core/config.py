"""Application configuration.

Every credential and tunable is read from the environment (a local ``.env`` is
picked up automatically) so that nothing sensitive has to live in source.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Alchemy ----------------------------------------------------------
    alchemy_api_key: str = ""
    alchemy_data_base_url: str = "https://api.g.alchemy.com/data/v1"
    alchemy_prices_base_url: str = "https://api.g.alchemy.com/prices/v1"

    # Networks requested from the portfolio endpoint. Note that Alchemy echoes
    # Polygon back as "matic-mainnet" even though it is requested as
    # "polygon-mainnet"; both spellings are handled downstream.
    alchemy_networks: list[str] = [
        "eth-mainnet",
        "base-mainnet",
        "arb-mainnet",
        "polygon-mainnet",
    ]

    # --- Polymarket -------------------------------------------------------
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"
    # Prediction markets are an optional enrichment, so they get a short
    # timeout: analysis must not stall when the provider is unreachable.
    polymarket_timeout_seconds: float = 8.0
    # After this many consecutive failures the client stops trying for
    # `polymarket_cooldown_seconds`. Without it, every analysis pays the full
    # timeout on every query when the provider is unreachable.
    polymarket_failure_threshold: int = 2
    polymarket_cooldown_seconds: float = 120.0
    # Resolve the Polymarket hosts over DNS-over-HTTPS. Some ISPs (e.g. Jio)
    # return a sinkhole address for them, so system DNS never connects.
    polymarket_dns_over_https: bool = True
    # Addressed by IP so the lookup itself does not depend on local DNS.
    dns_over_https_url: str = "https://1.1.1.1/dns-query"

    # --- HTTP -------------------------------------------------------------
    http_timeout_seconds: float = 30.0
    http_max_connections: int = 20

    # --- Portfolio scanning ----------------------------------------------
    # Heavily airdropped wallets return thousands of worthless spam tokens, so
    # the scan is bounded and dust is dropped before any analysis runs. Results
    # are NOT ordered by value, so a low cap silently hides real positions --
    # 20 pages (2,000 tokens) covers the wallets tested; when it is still not
    # enough the portfolio reports scan_truncated.
    portfolio_max_pages: int = 20
    portfolio_min_usd_value: float = 1.0

    # --- Quantitative defaults -------------------------------------------
    history_days: int = 180
    default_horizon_days: int = 90
    default_simulations: int = 10_000
    max_simulations: int = 200_000
    max_horizon_days: int = 1_095
    var_confidence: float = 0.95
    simulation_seed: int | None = None

    # --- Cache ------------------------------------------------------------
    analysis_cache_ttl_seconds: float = 300.0

    # --- Background refresh ----------------------------------------------
    # Every refresh_interval_minutes the API re-caches core price history and
    # Polymarket data in S3 and snapshots tracked wallets (services/refresh.py).
    # Turn off when the same jobs run on an EventBridge schedule instead.
    refresh_enabled: bool = True
    refresh_interval_minutes: int = 15
    refresh_snapshots: bool = True

    # --- Model (NVIDIA NIM) -----------------------------------------------
    # All model calls go to NVIDIA's hosted NIM API (OpenAI-compatible).
    # Key from https://build.nvidia.com (starts with nvapi-).
    nvidia_api_key: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Any NIM chat model with tool calling. Nemotron 3 Super was verified to
    # call the simulation tool correctly; availability varies by account.
    chat_model: str = "nvidia/nemotron-3-super-120b-a12b"
    chat_timeout_seconds: float = 60.0
    chat_max_tokens: int = 2048
    chat_max_history: int = 20

    # --- AWS --------------------------------------------------------------
    # Every AWS integration is optional; with aws_enabled false the service
    # runs entirely locally. In ECS, leave the key fields blank so boto3
    # resolves the task role instead.
    aws_enabled: bool = False
    aws_region: str = "ap-south-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    aws_profile: str = ""
    # Point the whole AWS stack at LocalStack or MinIO for local testing.
    aws_endpoint_url: str = ""

    # Secrets Manager — one JSON secret holding the API keys.
    aws_secret_id: str = ""

    # S3 — historical market data and portfolio snapshots.
    s3_bucket: str = ""

    # SQS — the Monte Carlo job queue.
    sqs_queue_url: str = ""
    # paths x horizon_days above which a run is queued rather than served inline.
    simulation_queue_threshold: int = 5_000_000

    # CloudWatch — custom metrics (logs arrive via stdout under ECS/Lambda).
    cloudwatch_enabled: bool = False

    # RDS PostgreSQL.
    database_url: str = ""
    database_pool_size: int = 5

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def alchemy_configured(self) -> bool:
        return bool(self.alchemy_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
