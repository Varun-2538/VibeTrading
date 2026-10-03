"""
Wallet sign-in endpoints.

Two steps: ask for a message, return a signature. The server holds the message it
issued in Redis, so verification never parses client-supplied text - see
services/auth_service.
"""
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from services.auth_service import (
    ARBITRUM_ONE,
    AuthError,
    NonceUnavailable,
    issue_challenge,
    issue_token,
    verify_signature,
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class VerifyRequest(BaseModel):
    address: str = Field(..., description="The address that signed")
    nonce: str = Field(..., description="The nonce from /api/auth/nonce")
    signature: str = Field(..., description="personal_sign output, 0x-prefixed")


@router.get("/nonce")
async def nonce(address: str = Query(..., description="Wallet address")) -> Dict[str, Any]:
    """
    Mint a challenge and return the exact message to sign.

    The client signs what comes back here verbatim. It must not rebuild the
    message itself: the server compares against its own stored copy, so a
    reconstruction that differs by a single character will not verify.
    """
    try:
        return await issue_challenge(address)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except NonceUnavailable as exc:
        # Redis is the nonce store. Without it no sign-in can be completed, and
        # saying so is better than issuing a message that could never verify.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )


@router.post("/verify")
async def verify(request: VerifyRequest) -> Dict[str, Any]:
    """Check the signature and return a session token."""
    try:
        owner_key = await verify_signature(
            address=request.address,
            nonce=request.nonce,
            signature=request.signature,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    return issue_token(owner_key)


@router.get("/config")
async def config() -> Dict[str, Any]:
    """What the wallet UI needs to know before it can prompt for a signature."""
    return {"chain_id": ARBITRUM_ONE, "chain_name": "Arbitrum One"}
