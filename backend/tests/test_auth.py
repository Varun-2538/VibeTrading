"""
Wallet sign-in: challenge, signature recovery, and session tokens.

Signing uses a fixed private key, so every assertion is deterministic and nothing
here touches a network or a node. The cache is faked, because the nonce store's
behaviour under a replay is exactly what several of these tests are about.
"""
import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings
from services import auth_service
from services.auth_service import (
    ARBITRUM_ONE,
    AuthError,
    NonceUnavailable,
    issue_challenge,
    issue_token,
    owner_key_for,
    read_token,
    verify_signature,
)

# Arbitrary fixed keys. Never used for anything real.
SIGNER = Account.from_key(
    "0x4c0883a69102937d6231471b5dbb6204fe512961708279f2e3a0dd0f9b1c1b3f"
)
IMPOSTOR = Account.from_key(
    "0x8da4ef21b864d2cc526dbdb2a120bd2874c36c9d0a1fb7f8c63d7f7a8b41de8f"
)


class FakeCache:
    """
    The parts of cache_service that sign-in uses.

    delete() reports whether it removed anything, mirroring the real client's
    `DEL` return, because single-use nonces depend on exactly that signal.
    """

    def __init__(self, writable: bool = True):
        self.store = {}
        self.writable = writable

    async def set(self, key, value, expiration=None):
        if not self.writable:
            return False
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return self.store.pop(key, None) is not None


@pytest.fixture
def cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(auth_service, "cache_service", fake)
    return fake


def sign(message: str, account=SIGNER) -> str:
    return account.sign_message(encode_defunct(text=message)).signature.hex()


# --- the challenge ---------------------------------------------------------


async def test_challenge_names_arbitrum_and_the_signer(cache):
    challenge = await issue_challenge(SIGNER.address)

    assert f"Chain ID: {ARBITRUM_ONE}" in challenge["message"]
    assert SIGNER.address in challenge["message"]
    assert challenge["nonce"] in challenge["message"]


async def test_challenge_rejects_a_malformed_address(cache):
    with pytest.raises(AuthError):
        await issue_challenge("not-an-address")


async def test_challenge_fails_loudly_when_the_nonce_cannot_be_stored(monkeypatch):
    """
    A challenge we cannot remember is a signature request for nothing.

    cache_service returns False rather than raising when Redis is gone, so
    without this check the user would be prompted to sign a message that could
    never verify.
    """
    monkeypatch.setattr(auth_service, "cache_service", FakeCache(writable=False))

    with pytest.raises(NonceUnavailable):
        await issue_challenge(SIGNER.address)


# --- verification ---------------------------------------------------------


async def test_valid_signature_yields_the_lowercased_owner_key(cache):
    challenge = await issue_challenge(SIGNER.address)

    owner_key = await verify_signature(
        address=SIGNER.address,
        nonce=challenge["nonce"],
        signature=sign(challenge["message"]),
    )

    assert owner_key == SIGNER.address.lower()


async def test_nonce_is_single_use(cache):
    """A replayed signature must not buy a second session."""
    challenge = await issue_challenge(SIGNER.address)
    signature = sign(challenge["message"])

    await verify_signature(
        address=SIGNER.address, nonce=challenge["nonce"], signature=signature
    )

    with pytest.raises(AuthError):
        await verify_signature(
            address=SIGNER.address, nonce=challenge["nonce"], signature=signature
        )


async def test_unknown_nonce_is_rejected(cache):
    with pytest.raises(AuthError):
        await verify_signature(
            address=SIGNER.address, nonce="never-issued", signature="0x00"
        )


async def test_signature_from_another_key_is_rejected(cache):
    challenge = await issue_challenge(SIGNER.address)

    with pytest.raises(AuthError):
        await verify_signature(
            address=SIGNER.address,
            nonce=challenge["nonce"],
            signature=sign(challenge["message"], account=IMPOSTOR),
        )


async def test_claimed_address_must_be_the_challenged_one(cache):
    """
    Requesting a challenge for your own address and submitting it as someone
    else's must fail, even though the signature itself is genuine.
    """
    challenge = await issue_challenge(SIGNER.address)

    with pytest.raises(AuthError):
        await verify_signature(
            address=IMPOSTOR.address,
            nonce=challenge["nonce"],
            signature=sign(challenge["message"]),
        )


async def test_signing_a_different_message_does_not_verify(cache):
    """
    The server compares against the message it stored, so a client that rebuilds
    the message itself and gets one character wrong is refused. This is the
    property that makes not parsing client SIWE text safe.
    """
    challenge = await issue_challenge(SIGNER.address)
    tampered = challenge["message"].replace(f"Chain ID: {ARBITRUM_ONE}", "Chain ID: 1")

    with pytest.raises(AuthError):
        await verify_signature(
            address=SIGNER.address,
            nonce=challenge["nonce"],
            signature=sign(tampered),
        )


async def test_a_failed_verification_still_burns_the_nonce(cache):
    """
    The nonce is spent before the signature is checked, so a wrong guess cannot
    be retried against the same challenge.
    """
    challenge = await issue_challenge(SIGNER.address)

    with pytest.raises(AuthError):
        await verify_signature(
            address=SIGNER.address,
            nonce=challenge["nonce"],
            signature=sign(challenge["message"], account=IMPOSTOR),
        )

    # Now the correct signature arrives, and is still refused.
    with pytest.raises(AuthError):
        await verify_signature(
            address=SIGNER.address,
            nonce=challenge["nonce"],
            signature=sign(challenge["message"]),
        )


# --- owner keys -----------------------------------------------------------


def test_address_casing_cannot_fragment_ownership():
    """
    EIP-55 varies the case of one address. If casing survived into the database,
    the same wallet would own two disjoint sets of rules depending on how the
    client happened to send it.
    """
    checksummed = SIGNER.address
    assert checksummed != checksummed.lower()  # guards the premise
    assert owner_key_for(checksummed) == owner_key_for(checksummed.lower())
    assert owner_key_for(checksummed) == checksummed.lower()


# --- session tokens -------------------------------------------------------


def test_token_round_trip():
    owner_key = SIGNER.address.lower()
    assert read_token(issue_token(owner_key)["token"]) == owner_key


def test_expired_token_is_rejected():
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    stale = jwt.encode(
        {"sub": SIGNER.address.lower(), "exp": int(past.timestamp())},
        settings.jwt_secret,
        algorithm="HS256",
    )

    with pytest.raises(AuthError):
        read_token(stale)


def test_token_signed_with_another_secret_is_rejected():
    forged = jwt.encode(
        {
            "sub": SIGNER.address.lower(),
            "exp": int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp()),
        },
        "not-the-real-secret",
        algorithm="HS256",
    )

    with pytest.raises(AuthError):
        read_token(forged)


def test_tampered_token_is_rejected():
    token = issue_token(SIGNER.address.lower())["token"]
    header, payload, signature = token.split(".")
    swapped = base64.urlsafe_b64encode(
        json.dumps({"sub": IMPOSTOR.address.lower()}).encode()
    ).decode().rstrip("=")

    with pytest.raises(AuthError):
        read_token(f"{header}.{swapped}.{signature}")


def test_unsigned_token_is_rejected():
    """
    The classic JWT failure: a token claiming alg "none" talks the verifier out of
    verifying. Pinning algorithms to HS256 is what stops it.
    """

    def b64(data: dict) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
        )

    unsigned = (
        f"{b64({'alg': 'none', 'typ': 'JWT'})}."
        f"{b64({'sub': IMPOSTOR.address.lower()})}."
    )

    with pytest.raises(AuthError):
        read_token(unsigned)


def test_token_without_a_subject_is_rejected():
    empty = jwt.encode(
        {"exp": int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())},
        settings.jwt_secret,
        algorithm="HS256",
    )

    with pytest.raises(AuthError):
        read_token(empty)
