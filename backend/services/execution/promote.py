"""
Queued fires become intents.

The sweep's job ends at one row: `DexTradeAction` returns "queued" and
`rule_engine.fire` writes that into the event it is already committing. Nothing else
happens in the API process. This is the other half - read those events, create the
intent, and move the event's status on.

`models/database.py` has no transaction that spans two statements, so the safety here
comes from a unique index instead: one intent per event, forever. That makes this
function safe to re-run, safe to run twice at once, and safe to interrupt anywhere -
which is a better property than a transaction would have given, because it also holds
across a restart.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.trade_plan import PARITY_VERSION

QUEUED = ("queued",)


def _at(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


async def promote_queued_events(*, intents, fires, policies, audit, limit: int = 20) -> int:
    """
    Returns how many intents were created. Zero is the normal answer.

    An event whose policy has since been disarmed is not promoted: the rule lost its
    permission between the fire and now, and the fire is not a licence that outlives
    it. The event is marked skipped so the reason is visible on the feed.
    """
    created = 0
    for event in await intents.queued_events(limit):
        result = dict(event["action_result"] or {})
        owner = event["owner_key"]
        rule_id = str(event["rule_id"])
        mode = event.get("account_mode") or "off"

        if mode == "off":
            continue  # nothing to do until the owner turns the account on

        policy = await policies.get(rule_id, owner)
        if policy is None or not policy["armed"]:
            await _skip(fires, audit, event, "no longer armed")
            continue
        if policy["parity_version"] != PARITY_VERSION:
            await _skip(fires, audit, event, "armed under different exit arithmetic")
            continue

        kind = result.get("kind") or "entry"
        reference = dict(result.get("reference") or {})
        not_after = _at(result.get("not_after"))
        if not_after is None:
            await _skip(fires, audit, event, "no deadline on the queued fire")
            continue
        if kind == "entry" and not_after < datetime.now(timezone.utc):
            # Never even reached the queue in time. Recorded rather than dropped,
            # because "why did my rule fire and nothing happen" deserves an answer.
            await _skip(fires, audit, event, "too late to be the same trade")
            continue

        intent = await intents.queue_from_event(
            owner_key=owner,
            rule_id=rule_id,
            event_id=int(event["event_id"]),
            kind=kind,
            mode=mode,
            venue=policy["venue"],
            market=policy["market"],
            side="sell" if kind != "entry" else "buy",
            plan=dict(policy["exit_plan"] or {}),
            reference=reference,
            parity_version=policy["parity_version"],
            not_after=not_after,
            position_id=result.get("position_id"),
        )
        if intent is None:
            # Already promoted. The unique index on event_id is what makes this
            # function safe to re-run, and this is it doing its job.
            continue

        await fires.set_action_result_if(
            int(event["event_id"]), QUEUED, "queued",
            {**result, "intent_id": str(intent["id"]), "state": "claimed_by_executor"},
        )
        await audit.record(
            owner_key=owner, actor="executor", reason=f"intent queued ({kind})",
            intent_id=str(intent["id"]), detail={"event_id": int(event["event_id"])},
        )
        created += 1
    return created


async def _skip(fires, audit, event: Dict[str, Any], reason: str) -> None:
    await fires.set_action_result_if(
        int(event["event_id"]), QUEUED, "skipped",
        {**dict(event["action_result"] or {}), "state": "skipped", "reason": reason},
    )
    await audit.record(
        owner_key=event["owner_key"], actor="executor", reason=f"not promoted: {reason}",
        detail={"event_id": int(event["event_id"])},
    )
