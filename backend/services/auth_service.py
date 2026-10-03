"""
Wallet sign-in: prove control of an address, get a session token.

The server builds the message it will later verify. That is the whole trick here:
because the exact string is minted server-side and stashed in Redis, verification
reconstructs it from stored fields instead of parsing what the client sends. No
SIWE parser means no SIWE parser bugs - no reordered fields, no injected
newlines, no nonce smuggled into the statement text.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import secrets

import jwt
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address

from config.settings import settings
from services.cache_service import cache_service

# Arbitrum One. Signing is chain-agnostic, so this is a deliberate constraint
# rather than a technical one: the chain a user signs on is the chain the rest of
# the product will operate on, and a session minted anywhere else is refused.
ARBITRUM_ONE = 42161

# Long enough that a slow signer is not timed out mid-prompt, short enough that
# an unspent nonce is not a standing invitation.
NONCE_TTL_SECONDS = 300

SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

_STATEMENT = (
    "Sign in to VibeTrading to build and view your own strategy rules. "
    "This proves you control this address. It does not authorise any "
    "transaction, approval or spending."
)


class AuthError(Exception):
    """Sign-in failed. The message is safe to show a user."""


class NonceUnavailable(Exception):
    """The nonce could not be stored, so no sign-in can be completed."""


def _nonce_key(nonce: str) -> str:
    return f"siwe:nonce:{nonce}"


def normalize_address(address: str) -> str:
    """
    Checksummed form, for display and for the signed message.

    Raises AuthError rather than ValueError so callers can map it to a 400
    without knowing which library rejected it.
    """
    try:
        return to_checksum_address(address)
    except Exception:
        raise AuthError("Not a valid Ethereum address")


def owner_key_for(address: str) -> str:
    """
    The form stored in the database.

    Lowercased, always. EIP-55 checksumming varies the case of the same address,
    so storing whatever arrived would let 0xAbC... and 0xabc... become two
    separate owners holding two separate sets of rules.
    """
    return normalize_address(address).lower()


def build_message(*, address: str, chain_id: int, nonce: str, issued_at: str) -> str:
    """The EIP-4361 message, in the shape wallets know how to render."""
    parsed = urlparse(settings.frontend_url)
    domain = parsed.netloc or settings.frontend_url
    uri = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else settings.frontend_url

    return (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{address}\n"
        f"\n"
        f"{_STATEMENT}\n"
        f"\n"
        f"URI: {uri}\n"
        f"Version: 1\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}"
    )


async def issue_challenge(address: str) -> Dict[str, Any]:
    """
    Mint a nonce and return the message to sign.

    Raises NonceUnavailable if Redis did not accept the write. cache_service
    fails soft everywhere else, which is right for a cache and wrong here: a
    challenge we cannot remember is a message the user signs for nothing.
    """
    checksummed = normalize_address(address)
    nonce = secrets.token_urlsafe(24)
    issued_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )

    stored = await cache_service.set(
        _nonce_key(nonce),
        {"address": checksummed, "chain_id": ARBITRUM_ONE, "issued_at": issued_at},
        NONCE_TTL_SECONDS,
    )
    if not stored:
        raise NonceUnavailable("Sign-in is temporarily unavailable. Please try again.")

    return {
        "message": build_message(
            address=checksummed,
            chain_id=ARBITRUM_ONE,
            nonce=nonce,
            issued_at=issued_at,
        ),
        "nonce": nonce,
        "chain_id": ARBITRUM_ONE,
        "expires_in": NONCE_TTL_SECONDS,
    }


async def verify_signature(*, address: str, nonce: str, signature: str) -> str:
    """
    Confirm the signature matches the challenge, and burn the nonce.

    Returns the owner key. Raises AuthError on any failure, with one message for
    every cause: which step failed is not the caller's business, and a specific
    error would tell someone probing exactly which half of a forgery to fix.
    """
    record: Optional[Dict[str, Any]] = await cache_service.get(_nonce_key(nonce))
    if not record:
        raise AuthError("This sign-in request expired. Please try again.")

    # Burn before verifying. DEL is atomic, so of two requests racing the same
    # nonce exactly one sees a delete, and the loser is refused even if it holds
    # a perfectly valid signature. That is what makes the nonce single-use, and
    # it is why this is not a read-then-write check.
    if not await cache_service.delete(_nonce_key(nonce)):
        raise AuthError("This sign-in request expired. Please try again.")

    expected = build_message(
        address=record["address"],
        chain_id=record["chain_id"],
        nonce=nonce,
        issued_at=record["issued_at"],
    )

    try:
        recovered = Account.recover_message(
            encode_defunct(text=expected), signature=signature
        )
    except Exception:
        raise AuthError("Signature could not be verified.")

    if recovered.lower() != record["address"].lower():
        raise AuthError("Signature could not be verified.")

    # The address the client claimed has to be the one we challenged; otherwise a
    # caller could request a challenge for their own address and submit it as
    # someone else's.
    if normalize_address(address).lower() != record["address"].lower():
        raise AuthError("Signature could not be verified.")

    return record["address"].lower()


def issue_token(owner_key: str) -> Dict[str, Any]:
    """A bearer token naming the address that signed."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=SESSION_TTL_SECONDS)

    token = jwt.encode(
        {"sub": owner_key, "iat": int(now.timestamp()), "exp": int(expires.timestamp())},
        settings.jwt_secret,
        algorithm="HS256",
    )

    return {
        "token": token,
        "address": owner_key,
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
    }


def read_token(token: str) -> str:
    """
    The owner key a token names, or AuthError.

    Algorithms are pinned to HS256 so a token cannot arrive claiming alg: none,
    which is the classic way a JWT check gets talked out of checking anything.
    """
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise AuthError("Session expired or invalid. Please sign in again.")

    owner_key = claims.get("sub")
    if not owner_key:
        raise AuthError("Session expired or invalid. Please sign in again.")
    return owner_key
