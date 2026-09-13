"""Execution schemas: a recommendation turned into swaps the wallet signs."""

from __future__ import annotations

from pydantic import BaseModel, Field

ADDRESS = r"^0x[0-9a-fA-F]{40}$"
TX_HASH = r"^0x[0-9a-fA-F]{64}$"


class ExecutionLeg(BaseModel):
    """One same-network swap. Nothing is sent until the wallet signs it."""

    id: str = Field(max_length=200)
    network: str
    chain: str
    chain_id: int
    sell_symbol: str
    sell_token: str = Field(pattern=ADDRESS, description="Contract address, or 0xEeee…EEeE for the native token")
    sell_decimals: int = Field(ge=0, le=36)
    sell_amount: str = Field(pattern=r"^[1-9][0-9]*$", description="Base units")
    sell_value_usd: float
    buy_symbol: str
    buy_token: str = Field(pattern=ADDRESS)
    buy_decimals: int = Field(ge=0, le=36)
    reason: str


class ExecutionPlan(BaseModel):
    address: str
    generated_at: str
    goal: str
    target_stablecoin_ratio: float
    current_stablecoin_ratio: float
    rebalance_required: bool
    legs: list[ExecutionLeg]
    skipped: list[str] = Field(description="Parts of the rebalance that could not become swaps, and why")
    slippage_bps: int
    swaps_configured: bool = Field(description="Whether the backend can fetch 0x quotes")


class PlanRequest(BaseModel):
    goal: str | None = Field(default=None, max_length=500)


class PreparedTransaction(BaseModel):
    kind: str = Field(description="approve-reset, approve or swap")
    description: str
    chain_id: int
    to: str
    data: str
    value: str = Field(description="Hex-encoded wei")


class LegQuote(BaseModel):
    leg_id: str
    chain_id: int
    sell_amount: str
    buy_amount: str
    min_buy_amount: str
    slippage_bps: int
    network_fee_wei: str | None = None
    transactions: list[PreparedTransaction] = Field(description="To be signed in order")


class ExecutionRecordRequest(BaseModel):
    leg_id: str = Field(max_length=200)
    chain_id: int
    kind: str = Field(pattern=r"^(approve-reset|approve|swap)$")
    tx_hash: str = Field(pattern=TX_HASH)


class ExecutionStatus(BaseModel):
    tx_hash: str
    chain_id: int
    status: str = Field(description="submitted, confirmed or failed")
    persisted: bool
