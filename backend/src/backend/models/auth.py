"""Wallet sign-in schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NonceResponse(BaseModel):
    nonce: str
    expires_at: str


class SignInRequest(BaseModel):
    message: str = Field(max_length=2000, description="The EIP-4361 message the wallet signed")
    signature: str = Field(pattern=r"^0x[0-9a-fA-F]{130}$")


class Session(BaseModel):
    address: str
    token: str = Field(description="Send as `Authorization: Bearer <token>`")
    expires_at: str
