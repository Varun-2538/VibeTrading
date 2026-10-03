"""
CRUD for strategy rules, plus the feed of what they fired.

Ownership is a wallet address proven by signature at sign-in and carried in a
bearer token - see require_owner. Every query is scoped by it, and a mismatch
returns 404 rather than 403, so a caller cannot use the response to confirm that
someone else's rule id exists.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from analysis.patterns import KINDS, PRESETS, SCALES, SOURCES
from services.auth_service import AuthError, read_token
from models.rule_schemas import (
    PATTERN_STATES,
    STRENGTH_ORDER,
    RuleCreate,
    RuleEventOut,
    RuleOut,
    RuleTestOut,
    RuleUpdate,
)
from repositories.rule_repository import RuleEventRepository, RuleRepository
from services.candle_service import CandleService, CandleFetchError, UnknownTimeframe
from services.rule_engine import RuleEngine

router = APIRouter(prefix="/api/rules", tags=["Rules"])


async def require_owner(authorization: Optional[str] = Header(default=None)) -> str:
    """
    The signed-in wallet address that owns the rules in this request.

    Unlike the browser-minted key this replaced, the caller cannot choose it: the
    address comes out of a token the server signed, and the server only signs one
    after recovering that address from an EIP-4361 signature. 401 rather than 400
    on a bad token, so the client knows to sign in again instead of treating it as
    a malformed request it could fix.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in with your wallet to manage strategy rules",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expected an Authorization: Bearer header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return read_token(token.strip())
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")


@router.get("/schema")
async def rule_schema() -> Dict[str, Any]:
    """The vocabulary the rule builder offers, mirroring /api/analysis/strictness."""
    return {
        "agents": ["pattern", "liquidity", "sequence"],
        "kinds": list(KINDS),
        "states": list(PATTERN_STATES),
        "strictness": list(PRESETS),
        "sources": list(SOURCES),
        "scales": list(SCALES),
        "strengths": list(STRENGTH_ORDER),
        "sides": ["support", "resistance"],
        "events": ["approach", "break"],
        "timeframes": CandleService.timeframes(),
    }


@router.get("/events", response_model=List[RuleEventOut])
async def list_events(
    owner_key: str = Depends(require_owner),
    rule_id: Optional[UUID] = Query(default=None),
    symbol: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    """What the owner's rules have fired, newest first."""
    return await RuleEventRepository.list_for_owner(
        owner_key,
        rule_id=str(rule_id) if rule_id else None,
        symbol=symbol,
        limit=limit,
    )


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    request: RuleCreate,
    owner_key: str = Depends(require_owner),
) -> Dict[str, Any]:
    """
    Arm a new rule.

    Parameters are validated by the discriminated union in RuleCreate, so a bad
    field is a 422 here rather than a rule that is accepted and never fires.
    """
    if request.timeframe not in CandleService.timeframes():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown timeframe '{request.timeframe}'. Expected one of: "
                f"{', '.join(CandleService.timeframes())}"
            ),
        )

    return await RuleRepository.create(
        owner_key=owner_key,
        name=request.name,
        agent=request.params.agent,
        symbol=request.symbol,
        timeframe=request.timeframe,
        params=request.params.model_dump(),
        cooldown_secs=request.cooldown_secs,
        persist_bars=request.resolved_persist_bars(),
    )


@router.get("", response_model=List[RuleOut])
async def list_rules(
    owner_key: str = Depends(require_owner),
    symbol: Optional[str] = Query(default=None),
    enabled: Optional[bool] = Query(default=None),
) -> List[Dict[str, Any]]:
    """The owner's rules, newest first."""
    return await RuleRepository.list_for_owner(owner_key, symbol=symbol, enabled=enabled)


@router.patch("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: UUID,
    request: RuleUpdate,
    owner_key: str = Depends(require_owner),
) -> Dict[str, Any]:
    """Enable, disable, rename or retune a rule."""
    fields: Dict[str, Any] = {}
    if request.name is not None:
        fields["name"] = request.name
    if request.enabled is not None:
        fields["enabled"] = request.enabled
    if request.cooldown_secs is not None:
        fields["cooldown_secs"] = request.cooldown_secs
    if request.persist_bars is not None:
        fields["persist_bars"] = request.persist_bars
    if request.params is not None:
        fields["params"] = request.params.model_dump()
        fields["agent"] = request.params.agent
        # Retuning changes what the rule means, so any half-built persistence
        # streak from the old parameters has to go.
        fields["pending"] = None

    rule = await RuleRepository.update(str(rule_id), owner_key, fields)
    if rule is None:
        raise _not_found()
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: UUID,
    owner_key: str = Depends(require_owner),
) -> None:
    """Delete a rule and its fire history."""
    if not await RuleRepository.delete(str(rule_id), owner_key):
        raise _not_found()


@router.post("/{rule_id}/test", response_model=RuleTestOut)
async def test_rule(
    rule_id: UUID,
    owner_key: str = Depends(require_owner),
    emit: bool = Query(
        default=False,
        description="Also record and broadcast the event, to exercise the alert path",
    ),
) -> Dict[str, Any]:
    """
    Evaluate the rule right now without waiting for the sweep.

    Reports why a matching signal would still not fire - cooldown, persistence
    or dedup - which is otherwise invisible and looks like a broken rule.
    """
    rule = await RuleRepository.get_for_owner(str(rule_id), owner_key)
    if rule is None:
        raise _not_found()

    lookback = int((rule["params"] or {}).get("lookback", 500))
    try:
        candles = await CandleService.get_candles(
            rule["symbol"], rule["timeframe"], lookback
        )
    except UnknownTimeframe as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except CandleFetchError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    signal, blocked = await RuleEngine.evaluate_rule(rule, candles[:-1], dry_run=True)

    if emit and signal is not None:
        event = await RuleEngine.fire(rule, signal)
        if event is None:
            blocked = "dedup"

    return {
        "would_fire": signal is not None and blocked is None,
        "blocked_by": blocked,
        "signal": signal.as_dict() if signal else None,
    }
