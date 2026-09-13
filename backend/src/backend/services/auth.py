"""Sign-In with Ethereum (EIP-4361).

Reading a wallet needs nothing: balances are public. Changing what Wallerina
stores for a wallet (its goal) or preparing trades from it needs proof that the
caller controls it. That proof is a signed EIP-4361 message:

1. ``GET /api/auth/nonce`` issues a single-use nonce.
2. The wallet signs a sign-in message containing it (``personal_sign``).
3. ``POST /api/auth/verify`` checks the message and signature, uses the nonce
   up, and returns a session token: an HMAC-signed claim of the address and
   its expiry.

Only externally owned accounts are supported. A smart-contract wallet signs
through EIP-1271, which needs an on-chain call this module does not make.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from eth_account import Account
from eth_account.messages import encode_defunct

from backend.assets.registry import CHAIN_IDS
from backend.aws import database
from backend.core.config import get_settings
from backend.models.auth import Session

NONCE_TTL = timedelta(minutes=10)
CLOCK_SKEW = timedelta(minutes=2)

ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
HEADER = re.compile(r"^(?P<domain>\S+) wants you to sign in with your Ethereum account:$")
FIELDS = {"URI", "Version", "Chain ID", "Nonce", "Issued At", "Expiration Time", "Not Before", "Request ID"}
REQUIRED_FIELDS = ("URI", "Version", "Chain ID", "Nonce", "Issued At")


class AuthError(ValueError):
    """Sign-in failed. The message is safe to show to the user."""


# Nonces live in the database so every API process shares them; this holds them
# when there is no database.
_memory_nonces: dict[str, datetime] = {}

# Used when SESSION_SECRET is unset, so sessions last only as long as the process.
_process_secret = secrets.token_bytes(32)


def _now() -> datetime:
    return datetime.now(UTC)


async def issue_nonce() -> tuple[str, datetime]:
    nonce = secrets.token_hex(16)
    expires_at = _now() + NONCE_TTL

    if not await database.store_nonce(nonce, expires_at):
        for stale in [key for key, expiry in _memory_nonces.items() if expiry <= _now()]:
            del _memory_nonces[stale]
        _memory_nonces[nonce] = expires_at

    return nonce, expires_at


async def consume_nonce(nonce: str) -> bool:
    """Use a nonce up. True only the first time, and only before it expires."""
    if nonce in _memory_nonces:
        return _memory_nonces.pop(nonce) > _now()
    return bool(await database.consume_nonce(nonce))


@dataclass(frozen=True)
class SignInMessage:
    domain: str
    address: str
    uri: str
    version: str
    chain_id: int
    nonce: str
    issued_at: datetime
    expiration_time: datetime | None


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AuthError(f"The sign-in message has an invalid {name}") from error
    if parsed.tzinfo is None:
        raise AuthError(f"The sign-in message's {name} has no timezone")
    return parsed


def parse_message(text: str) -> SignInMessage:
    lines = text.split("\n")
    header = HEADER.match(lines[0]) if lines else None
    if header is None or len(lines) < 2 or not ADDRESS.fullmatch(lines[1].strip()):
        raise AuthError("Not a sign-in message")

    fields: dict[str, str] = {}
    for line in lines[2:]:
        key, separator, value = line.partition(": ")
        if separator and key in FIELDS:
            fields.setdefault(key, value.strip())

    missing = [key for key in REQUIRED_FIELDS if key not in fields]
    if missing:
        raise AuthError(f"The sign-in message is missing {', '.join(missing)}")

    try:
        chain_id = int(fields["Chain ID"])
    except ValueError as error:
        raise AuthError("The sign-in message has an invalid Chain ID") from error

    return SignInMessage(
        domain=header["domain"],
        address=lines[1].strip(),
        uri=fields["URI"],
        version=fields["Version"],
        chain_id=chain_id,
        nonce=fields["Nonce"],
        issued_at=_timestamp(fields["Issued At"], "Issued At"),
        expiration_time=(
            _timestamp(fields["Expiration Time"], "Expiration Time") if "Expiration Time" in fields else None
        ),
    )


async def verify_sign_in(message: str, signature: str) -> Session:
    settings = get_settings()
    parsed = parse_message(message)

    # The domain binds the signature to this site, so a message signed for a
    # phishing page cannot be replayed here.
    if parsed.domain not in settings.siwe_domain_list:
        raise AuthError("This sign-in message was made for a different site")
    if parsed.version != "1":
        raise AuthError("Unsupported sign-in message version")
    if parsed.chain_id not in CHAIN_IDS.values():
        raise AuthError("Sign in on Ethereum, Base, Arbitrum or Polygon")

    now = _now()
    if parsed.issued_at > now + CLOCK_SKEW or now - parsed.issued_at > NONCE_TTL:
        raise AuthError("This sign-in message has expired; sign in again")
    if parsed.expiration_time is not None and parsed.expiration_time <= now:
        raise AuthError("This sign-in message has expired; sign in again")

    try:
        signer = Account.recover_message(encode_defunct(text=message), signature=signature)
    except Exception as error:
        raise AuthError("The signature could not be verified") from error

    if signer.lower() != parsed.address.lower():
        raise AuthError("The signature was not made by the address in the message")

    # Last, so a forged message cannot burn someone else's nonce.
    if not await consume_nonce(parsed.nonce):
        raise AuthError("This sign-in was already used or has expired; sign in again")

    return issue_session(signer)


def _secret() -> bytes:
    configured = get_settings().session_secret
    return configured.encode() if configured else _process_secret


def _mac(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def issue_session(address: str) -> Session:
    expires_at = _now() + timedelta(hours=get_settings().session_ttl_hours)
    payload = f"{address.lower()}.{int(expires_at.timestamp())}"
    return Session(address=address, token=f"{payload}.{_mac(payload)}", expires_at=expires_at.isoformat())


def read_session(token: str) -> str | None:
    """The lowercased address a token was issued to, or None if invalid or expired."""
    parts = token.split(".")
    if len(parts) != 3:
        return None

    address, expires, mac = parts
    if not ADDRESS.fullmatch(address) or not expires.isdigit():
        return None
    if not hmac.compare_digest(mac, _mac(f"{address}.{expires}")):
        return None
    if int(expires) <= _now().timestamp():
        return None
    return address
