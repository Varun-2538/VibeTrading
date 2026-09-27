"""
The execution surface: an account's rails, and which rules may trade.

Nothing here places a trade. What it does is decide, and record, whether a rule
has earned the right to - which is why arming is its own endpoint rather than a
field on the rule. `strategy_rules.action` is what the owner declared;
`execution_policies` is what the server agreed to, and the agreement can only be
made through this route, after a backtest has passed.

Ownership works as it does everywhere else: the wallet comes out of a token the
server signed, every query is scoped by it, and a mismatch is 404 rather than 403
so a caller cannot use the response to confirm someone else's rule id exists.

One thing this route does not yet have, and must before live mode: a fresh
signature over the specific change. A bearer token in localStorage is the right
ceiling for reading and editing rules and the wrong one for authorising spend -
frontend/lib/session.ts says so itself. Arming is gated on a passing backtest and
on the account being off by default, so the ceiling holds until then.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from controllers.rules_controller import require_owner
from models.execution_schemas import AccountSettings, ArmRequest, PreflightThresholds
from repositories.backtest_repository import BacktestRepository
from repositories.execution_repository import (
    ExecutionAccountRepository,
    ExecutionPolicyRepository,
    ExecutionSettingsRepository,
)
from repositories.rule_repository import RuleRepository
from services.execution.preflight import check
from services.trade_plan import PARITY_VERSION

router = APIRouter(prefix="/api/execution", tags=["Execution"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule")


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _account(owner_key: str, row: Optional[Dict[str, Any]], globally_enabled: bool) -> Dict[str, Any]:
    """
    An account that has never been configured reads as the defaults rather than as
    an error: "off, and these are the caps you would start from".
    """
    defaults = AccountSettings()
    base = {
        "owner_key": owner_key,
        "configured": row is not None,
        "mode": defaults.mode,
        "kill_switch": False,
        "equity_usd": defaults.equity_usd,
        "max_notional_usd": defaults.max_notional_usd,
        "max_concurrent_positions": defaults.max_concurrent_positions,
        "max_trades_per_day": defaults.max_trades_per_day,
        "daily_loss_limit_usd": defaults.daily_loss_limit_usd,
        "halted_reason": None,
    }
    if row is not None:
        base.update({k: row[k] for k in base if k in row})
        base["equity_usd"] = float(row["equity_usd"])
        base["max_notional_usd"] = float(row["max_notional_usd"])
        base["daily_loss_limit_usd"] = float(row["daily_loss_limit_usd"])
    # The global brake is reported alongside, because an account that looks armed
    # while execution is switched off is the most confusing state to debug.
    base["execution_enabled"] = globally_enabled
    base["parity_version"] = PARITY_VERSION
    return base


def _policy(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rule_id": str(row["rule_id"]),
        "armed": row["armed"],
        "venue": row["venue"],
        "market": row["market"],
        "exit": row["exit_plan"],
        "policy": row["policy"],
        "parity_version": row["parity_version"],
        "parity_current": row["parity_version"] == PARITY_VERSION,
        "backtest_job_id": str(row["backtest_job_id"]) if row["backtest_job_id"] else None,
        "preflight": row["preflight"],
        "armed_at": _iso(row["armed_at"]),
        "disarmed_reason": row["disarmed_reason"],
    }


@router.get("/account")
async def get_account(owner_key: str = Depends(require_owner)) -> Dict[str, Any]:
    settings = await ExecutionSettingsRepository.get()
    row = await ExecutionAccountRepository.get(owner_key)
    return _account(owner_key, row, bool(settings["enabled"]))


@router.put("/account")
async def put_account(
    body: AccountSettings, owner_key: str = Depends(require_owner)
) -> Dict[str, Any]:
    """
    Set this wallet's rails. Every field is a ceiling, and saving them cannot
    clear a halt that reconciliation set.
    """
    row = await ExecutionAccountRepository.upsert(owner_key, body.model_dump())
    settings = await ExecutionSettingsRepository.get()
    return _account(owner_key, row, bool(settings["enabled"]))


@router.post("/kill")
async def kill(owner_key: str = Depends(require_owner)) -> Dict[str, Any]:
    """
    Stop opening anything, now.

    It does not stop closing: exits only ever reduce exposure, and a switch that
    prevented them would be a trap rather than a safety rail.
    """
    row = await ExecutionAccountRepository.set_kill_switch(owner_key, True)
    if row is None:
        row = await ExecutionAccountRepository.upsert(owner_key, AccountSettings().model_dump())
        row = await ExecutionAccountRepository.set_kill_switch(owner_key, True)
    settings = await ExecutionSettingsRepository.get()
    return _account(owner_key, row, bool(settings["enabled"]))


@router.delete("/kill")
async def unkill(owner_key: str = Depends(require_owner)) -> Dict[str, Any]:
    row = await ExecutionAccountRepository.set_kill_switch(owner_key, False)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No execution account yet")
    settings = await ExecutionSettingsRepository.get()
    return _account(owner_key, row, bool(settings["enabled"]))


@router.get("/policies")
async def list_policies(owner_key: str = Depends(require_owner)) -> List[Dict[str, Any]]:
    return [_policy(row) for row in await ExecutionPolicyRepository.list_for_owner(owner_key)]


@router.post("/rules/{rule_id}/preflight")
async def run_preflight(
    rule_id: UUID,
    body: ArmRequest,
    owner_key: str = Depends(require_owner),
) -> Dict[str, Any]:
    """Run the gate without arming anything, so a refusal can be read and fixed."""
    result = await _gate(rule_id, body, owner_key)
    return result.as_dict()


@router.post("/rules/{rule_id}/arm")
async def arm_rule(
    rule_id: UUID,
    body: ArmRequest,
    owner_key: str = Depends(require_owner),
) -> Dict[str, Any]:
    """
    Arm a rule for execution against a named backtest.

    409 with every reason it failed, not the first: an owner fixing them one at a
    time learns nothing about the rest.
    """
    result = await _gate(rule_id, body, owner_key)
    if not result.passed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "This rule cannot be armed yet.", "reasons": result.reasons},
        )

    policy = body.action.model_dump()
    exit_plan = policy.pop("exit")
    row = await ExecutionPolicyRepository.arm(
        str(rule_id),
        owner_key,
        venue=body.action.venue,
        market=body.action.market,
        exit_plan=exit_plan,
        policy=policy,
        parity_version=PARITY_VERSION,
        backtest_job_id=body.backtest_job_id,
        preflight=result.as_dict(),
    )
    return _policy(row)


@router.delete("/rules/{rule_id}/arm")
async def disarm_rule(rule_id: UUID, owner_key: str = Depends(require_owner)) -> Dict[str, Any]:
    rule = await RuleRepository.get_for_owner(str(rule_id), owner_key)
    if rule is None:
        raise _not_found()
    await ExecutionPolicyRepository.disarm(str(rule_id), "disarmed by owner", owner_key)
    row = await ExecutionPolicyRepository.get(str(rule_id), owner_key)
    if row is None:
        return {"rule_id": str(rule_id), "armed": False, "disarmed_reason": "never armed"}
    return _policy(row)


async def _gate(rule_id: UUID, body: ArmRequest, owner_key: str):
    rule = await RuleRepository.get_for_owner(str(rule_id), owner_key)
    if rule is None:
        raise _not_found()
    job = await BacktestRepository.get_for_owner(body.backtest_job_id, owner_key)
    return check(
        rule,
        body.action,
        job,
        thresholds=body.thresholds or PreflightThresholds(),
        now=datetime.now(timezone.utc),
    )
