"""
CRUD for strategy rules, plus the feed of what they fired.

Ownership comes from an `X-Owner-Key` header. That key is a namespace, not an
authentication credential - see require_owner_key. Every query is scoped by it
and a mismatch returns 404 rather than 403, so a caller cannot use the response
to confirm that someone else's rule id exists.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from analysis.patterns import KINDS, PRESETS, SCALES, SOURCES
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


async def require_owner_key(x_owner_key: Optional[str] = Header(default=None)) -> str:
    """
    The caller's rule namespace.

    This is NOT authentication: anyone holding the key can act as its owner, and
    the server never verifies who minted it. It is sufficient only because a
    Phase 1 rule can do nothing but raise an alert. Before a rule can spend
    money this must be replaced with a signed-in identity.
    """
    if not x_owner_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Owner-Key header",
        )
    try:
        UUID(x_owner_key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Owner-Key must be a UUID",
        )
    return x_owner_key


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")


@router.get("/schema")
async def rule_schema() -> Dict[str, Any]:
    """The vocabulary the rule builder offers, mirroring /api/analysis/strictness."""
    return {
        "agents": ["pattern", "liquidity"],
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
    owner_key: str = Depends(require_owner_key),
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
    owner_key: str = Depends(require_owner_key),
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
        persist_bars=request.persist_bars,
    )


@router.get("", response_model=List[RuleOut])
async def list_rules(
    owner_key: str = Depends(require_owner_key),
    symbol: Optional[str] = Query(default=None),
    enabled: Optional[bool] = Query(default=None),
) -> List[Dict[str, Any]]:
    """The owner's rules, newest first."""
    return await RuleRepository.list_for_owner(owner_key, symbol=symbol, enabled=enabled)


@router.patch("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: UUID,
    request: RuleUpdate,
    owner_key: str = Depends(require_owner_key),
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
    owner_key: str = Depends(require_owner_key),
) -> None:
    """Delete a rule and its fire history."""
    if not await RuleRepository.delete(str(rule_id), owner_key):
        raise _not_found()


@router.post("/{rule_id}/test", response_model=RuleTestOut)
async def test_rule(
    rule_id: UUID,
    owner_key: str = Depends(require_owner_key),
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
