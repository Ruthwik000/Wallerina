"""Portfolio and wallet schemas (specification section 8)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.assets.registry import AssetClass


class Holding(BaseModel):
    symbol: str
    name: str | None = None
    network: str
    chain: str
    contract_address: str | None = Field(
        default=None, description="None for the network's native token"
    )
    quantity: float
    price_usd: float
    value_usd: float
    portfolio_ratio: float = Field(ge=0, le=1)
    classification: AssetClass
    decimals: int | None = None

    @property
    def is_stable(self) -> bool:
        return self.classification is AssetClass.STABLECOIN


class ChainExposure(BaseModel):
    network: str
    chain: str
    value_usd: float
    ratio: float


class Portfolio(BaseModel):
    address: str
    total_value_usd: float
    holdings: list[Holding]

    stablecoin_value_usd: float
    volatile_value_usd: float
    unknown_value_usd: float

    stablecoin_ratio: float = Field(ge=0, le=1)
    volatile_ratio: float = Field(ge=0, le=1)

    concentration: float = Field(
        description="Herfindahl-Hirschman index over holding weights, 0-1"
    )
    chains: list[ChainExposure]

    holdings_scanned: int = Field(
        description="Tokens returned by the provider before spam and dust filtering"
    )
    holdings_kept: int
    scan_truncated: bool = Field(
        default=False,
        description=(
            "True when the page limit was reached before the wallet was fully "
            "scanned, so holdings and totals may be understated"
        ),
    )
