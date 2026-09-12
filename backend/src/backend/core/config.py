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

    @property
    def alchemy_configured(self) -> bool:
        return bool(self.alchemy_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
