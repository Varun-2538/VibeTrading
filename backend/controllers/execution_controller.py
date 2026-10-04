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

from config import settings
from controllers.rules_controller import require_owner
from models.execution_schemas import AccountSettings, ArmRequest, PreflightThresholds
from repositories.backtest_repository import BacktestRepository
from repositories.execution_repository import (
    ExecutionAccountRepository,
    ExecutionAuditRepository,
    ExecutionFillRepository,
    ExecutionIntentRepository,
    ExecutionOrderRepository,
    ExecutionPolicyRepository,
    ExecutionPositionRepository,
    ExecutionSettingsRepository,
)
from repositories.rule_repository import RuleRepository
from services.execution.markets import CHAINS, factory_address
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
    # The address a vault owner grants to. Published rather than configured in the
    # browser: one source of truth, so a redeployed executor cannot leave owners
    # granting permission to an address that no longer signs anything.
    base["operator_address"] = settings.executor_address or None
    # Where vaults can live, from the same reasoning: the factory a browser deploys
    # through is the one the executor resolves vaults from, so it is published here
    # rather than built into the frontend. A chain with no factory is listed with
    # null, so the panel can say it is not open yet instead of hiding it.
    base["chains"] = [
        {
            "key": info.key,
            "chain_id": info.chain_id,
            "name": info.name,
            "venue": info.venue,
            "stable": info.stable,
            "stable_symbol": info.stable_symbol,
            "factory": factory_address(info) or None,
            "markets": dict(info.markets),
            "stock_markets": list(info.stock_markets),
            "explorer": info.explorer,
        }
        for info in CHAINS
    ]
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


def _position(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "rule_id": str(row["rule_id"]),
        "status": row["status"],
        "mode": row["mode"],
        "venue": row["venue"],
        "market": row["market"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "direction": "long" if int(row["direction"]) == 1 else "short",
        "entry_price": _num(row["entry_price"]),
        "qty": _num(row["qty"]),
        "notional_usd": _num(row["notional_usd"]),
        "stop_price": _num(row["stop_price"]),
        "target_price": _num(row["target_price"]),
        "deadline": _iso(row["deadline_bar_time"]),
        "opened_at": _iso(row["opened_at"]),
        "closed_at": _iso(row["closed_at"]),
        "exit_price": _num(row["exit_price"]),
        "exit_reason": row["exit_reason"],
        "realised_pnl_usd": _num(row["realised_pnl_usd"]),
        "realised_r": _num(row["realised_r"]),
        # Where the stop and the target came from, and how far the fill landed from
        # the price the report would have used. This is the parity measurement.
        "reference": row["reference"],
    }


def _num(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


@router.get("/positions")
async def list_positions(owner_key: str = Depends(require_owner)) -> List[Dict[str, Any]]:
    return [_position(row) for row in await ExecutionPositionRepository.list_for_owner(owner_key)]


@router.get("/positions/{position_id}")
async def get_position(
    position_id: UUID, owner_key: str = Depends(require_owner)
) -> Dict[str, Any]:
    """
    The whole chain behind one position, in order, for someone who wants to dispute a
    fill.

    Why it traded (the rule and the policy that armed it, with the backtest that
    passed), what was decided (the intent, its plan and its sizing), what was sent
    (every order, with the request and the response stored verbatim and never parsed
    for control flow), what came back (every fill, with fees, gas and a transaction
    reference), and every state change with the actor that made it.
    """
    row = await ExecutionPositionRepository.get(str(position_id), owner_key)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such position")

    policy = await ExecutionPolicyRepository.get(str(row["rule_id"]), owner_key)
    orders = await ExecutionOrderRepository.for_intent(str(row["entry_intent_id"]))
    return {
        "position": _position(row),
        "plan": row["plan"],
        "parity_version": row["parity_version"],
        "parity_current": row["parity_version"] == PARITY_VERSION,
        "policy": _policy(policy) if policy else None,
        "orders": [
            {
                "client_order_id": o["client_order_id"],
                "leg": o["leg"],
                "status": o["status"],
                "venue_order_id": o["venue_order_id"],
                "submitted_at": _iso(o["submitted_at"]),
                "acked_at": _iso(o["acked_at"]),
                "request": o["request"],
                "response": o["response"],
                "error": o["error"],
            }
            for o in orders
        ],
        "fills": [
            {
                "price": _num(f["price"]),
                "qty": _num(f["qty"]),
                "fee_usd": _num(f["fee_usd"]),
                "gas_usd": _num(f["gas_usd"]),
                "tx_ref": f["tx_ref"],
                "filled_at": _iso(f["filled_at"]),
                "venue_fill_id": f["venue_fill_id"],
            }
            for f in await ExecutionFillRepository.for_position(str(position_id))
        ],
        "audit": [
            {
                "at": _iso(a["at"]),
                "actor": a["actor"],
                "from": a["from_status"],
                "to": a["to_status"],
                "reason": a["reason"],
                "detail": a["detail"],
            }
            for a in await ExecutionAuditRepository.for_position(str(position_id))
        ],
    }


@router.get("/intents")
async def list_intents(
    owner_key: str = Depends(require_owner),
    status_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """The queue, for working out why a rule fired and nothing happened."""
    rows = await ExecutionIntentRepository.list_for_owner(owner_key, status_filter)
    return [
        {
            "id": str(row["id"]),
            "rule_id": str(row["rule_id"]),
            "kind": row["kind"],
            "status": row["status"],
            "mode": row["mode"],
            "attempts": row["attempts"],
            "created_at": _iso(row["created_at"]),
            "not_after": _iso(row["not_after"]),
            "claimed_by": row["claimed_by"],
            "error": row["error"],
            "sizing": row["sizing"],
        }
        for row in rows
    ]


@router.get("/health")
async def health(owner_key: str = Depends(require_owner)) -> Dict[str, Any]:
    """
    Whether execution is actually running, as opposed to armed.

    The container's own healthcheck reads the heartbeat file; this is for a person
    asking why their armed rule has not traded. Stuck intents and orders in doubt are
    the two numbers that say "something is wrong" rather than "nothing has happened".
    """
    settings = await ExecutionSettingsRepository.get()
    account = await ExecutionAccountRepository.get(owner_key)
    stuck = await ExecutionIntentRepository.stuck()
    in_doubt = await ExecutionOrderRepository.in_doubt()
    return {
        "execution_enabled": bool(settings["enabled"]),
        "globally_halted": settings["halted_reason"],
        "mode": (account or {}).get("mode", "off"),
        "kill_switch": bool((account or {}).get("kill_switch")),
        "halted_reason": (account or {}).get("halted_reason"),
        "parity_version": PARITY_VERSION,
        "queued": len(await ExecutionIntentRepository.list_for_owner(owner_key, "queued")),
        "stuck_intents": len([i for i in stuck if i["owner_key"] == owner_key]),
        "orders_in_doubt": len([o for o in in_doubt if o["owner_key"] == owner_key]),
        "open_positions": len([
            p for p in await ExecutionPositionRepository.list_for_owner(owner_key)
            if p["status"] in ("opening", "open", "closing")
        ]),
    }
