"""Market and prediction-market schemas (specification sections 10 and later)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PricePoint(BaseModel):
    timestamp: str
    value: float


class PriceHistory(BaseModel):
    symbol: str
    currency: str = "usd"
    points: list[PricePoint]


class PredictionMarket(BaseModel):
    """A single Polymarket binary market relevant to a held asset."""

    question: str
    event: str | None = None
    probability: float | None = Field(
        default=None, description="Price of the YES outcome, read as a probability"
    )
    yes_token_id: str | None = None
    liquidity: float = 0.0
    volume: float = 0.0
    probability_change_24h: float | None = Field(
        default=None,
        description=(
            "Relative change in the YES price over 24 hours. None when the "
            "market is too thin to report a meaningful move."
        ),
    )
    direction: str | None = Field(
        default=None,
        description="'downside' for markets resolving on a price fall, 'upside' on a rise",
    )
    threshold: float | None = Field(
        default=None,
        description="The price level the market resolves on, in USD, when one is stated",
    )
    end_date: str | None = Field(
        default=None,
        description="ISO date the market resolves. Probabilities are only comparable within one expiry.",
    )
    source: str = Field(
        default="polymarket",
        description="Exchange the quote came from. Carried so an explanation can cite it.",
    )


class AssetPredictionMarkets(BaseModel):
    asset: str
    markets: list[PredictionMarket]


class MarketStress(BaseModel):
    """Liquidity-weighted downside signal derived from prediction markets.

    This is a deliberately simple, transparent mapping. Interpreting prediction
    markets properly is the job of the (not yet built) market analysis agent;
    until then this provides a bounded, auditable volatility adjustment.
    """

    score: float = Field(ge=0, le=1, description="0 = calm, 1 = maximum observed stress")
    volatility_multiplier: float = Field(
        ge=1.0, description="Factor applied to estimated volatility in simulation"
    )
    markets_considered: int
    total_liquidity: float
    available: bool = Field(
        default=True, description="False when prediction-market data could not be fetched"
    )
