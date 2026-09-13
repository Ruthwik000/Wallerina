"""Wallet sign-in (EIP-4361) and the goal endpoint it protects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from backend import main
from backend.core.config import get_settings
from backend.services import auth


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    monkeypatch.setenv("RDS_HOST", "")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("SIWE_DOMAINS", "")
    get_settings.cache_clear()
    auth._memory_nonces.clear()
    main.limiter.reset()
    yield
    get_settings.cache_clear()
    auth._memory_nonces.clear()


def sign_in_message(address, nonce, *, domain="localhost:3000", chain_id=8453, issued_at=None):
    issued = (issued_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    return (
        f"{domain} wants you to sign in with your Ethereum account:\n{address}\n\n"
        "Sign in to Wallerina.\n\n"
        f"URI: http://{domain}\nVersion: 1\nChain ID: {chain_id}\nNonce: {nonce}\nIssued At: {issued}"
    )


def sign(account, message):
    return "0x" + bytes(Account.sign_message(encode_defunct(text=message), account.key).signature).hex()


class TestVerify:
    @pytest.mark.asyncio
    async def test_a_valid_signature_starts_a_session_for_the_signer(self):
        account = Account.create()
        nonce, _ = await auth.issue_nonce()
        message = sign_in_message(account.address, nonce)

        session = await auth.verify_sign_in(message, sign(account, message))

        assert session.address == account.address
        assert auth.read_session(session.token) == account.address.lower()

    @pytest.mark.asyncio
    async def test_a_sign_in_cannot_be_replayed(self):
        account = Account.create()
        nonce, _ = await auth.issue_nonce()
        message = sign_in_message(account.address, nonce)
        signature = sign(account, message)
        await auth.verify_sign_in(message, signature)

        with pytest.raises(auth.AuthError, match="already used"):
            await auth.verify_sign_in(message, signature)

    @pytest.mark.asyncio
    async def test_a_message_for_another_site_is_rejected(self):
        account = Account.create()
        nonce, _ = await auth.issue_nonce()
        message = sign_in_message(account.address, nonce, domain="phishing.example")

        with pytest.raises(auth.AuthError, match="different site"):
            await auth.verify_sign_in(message, sign(account, message))

    @pytest.mark.asyncio
    async def test_a_signature_from_another_key_is_rejected(self):
        victim, attacker = Account.create(), Account.create()
        nonce, _ = await auth.issue_nonce()
        message = sign_in_message(victim.address, nonce)

        with pytest.raises(auth.AuthError, match="not made by the address"):
            await auth.verify_sign_in(message, sign(attacker, message))
        assert nonce in auth._memory_nonces, "a forged attempt must not burn the real nonce"

    @pytest.mark.asyncio
    async def test_stale_messages_and_unknown_nonces_are_rejected(self):
        account = Account.create()
        nonce, _ = await auth.issue_nonce()
        stale = sign_in_message(account.address, nonce, issued_at=datetime.now(UTC) - timedelta(minutes=20))
        invented = sign_in_message(account.address, "0123456789abcdef")

        with pytest.raises(auth.AuthError, match="expired"):
            await auth.verify_sign_in(stale, sign(account, stale))
        with pytest.raises(auth.AuthError, match="already used or has expired"):
            await auth.verify_sign_in(invented, sign(account, invented))

    @pytest.mark.parametrize(
        "text",
        ["hello", "localhost:3000 wants you to sign in with your Ethereum account:\nnot-an-address"],
    )
    def test_malformed_messages_are_rejected(self, text):
        with pytest.raises(auth.AuthError):
            auth.parse_message(text)


class TestSessions:
    def test_a_tampered_token_is_rejected(self):
        session = auth.issue_session("0x" + "a" * 40)
        address, expires, mac = session.token.split(".")

        assert auth.read_session(f"{'0x' + 'b' * 40}.{expires}.{mac}") is None
        assert auth.read_session(f"{address}.{int(expires) + 999}.{mac}") is None
        assert auth.read_session("garbage") is None

    def test_an_expired_token_is_rejected(self, monkeypatch):
        monkeypatch.setenv("SESSION_TTL_HOURS", "-1")
        get_settings.cache_clear()

        assert auth.read_session(auth.issue_session("0x" + "a" * 40).token) is None


class TestGoalEndpoint:
    def test_saving_a_goal_needs_that_wallets_session(self):
        client = TestClient(main.app)
        owner, other = Account.create(), Account.create()

        nonce = client.get("/api/auth/nonce").json()["nonce"]
        message = sign_in_message(owner.address, nonce)
        response = client.post("/api/auth/verify", json={"message": message, "signature": sign(owner, message)})
        assert response.status_code == 200
        token = response.json()["token"]

        body = {"goal": "Preserve capital"}
        assert client.put(f"/api/goal/{owner.address}", json=body).status_code == 401
        assert (
            client.put(f"/api/goal/{other.address}", json=body, headers={"Authorization": f"Bearer {token}"}).status_code
            == 403
        )
        saved = client.put(f"/api/goal/{owner.address}", json=body, headers={"Authorization": f"Bearer {token}"})
        assert saved.status_code == 200
        assert saved.json()["goal"] == "Preserve capital"

    def test_a_bad_signature_is_a_401_not_a_500(self):
        client = TestClient(main.app)
        account = Account.create()
        nonce = client.get("/api/auth/nonce").json()["nonce"]
        message = sign_in_message(account.address, nonce)

        response = client.post("/api/auth/verify", json={"message": message, "signature": "0x" + "1" * 130})

        assert response.status_code == 401
