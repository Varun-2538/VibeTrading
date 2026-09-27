"""
Claim an intent, send exactly one venue write, record what came back.

The order of operations is the whole file, and it is chosen so that every way this
can be interrupted leaves a state that can be read afterwards:

1. the order row is inserted **before** the venue is called, carrying the
   client_order_id - so a process that dies inside the swap leaves "submitting",
   which reconciliation knows how to ask about;
2. `VenueRejected` means it definitely did not happen, so the intent may go back on
   the queue;
3. `VenueUnknown` means we do not know, so it may **never** be retried directly.
   It becomes needs_reconcile and waits to be told what is true.

That distinction is the only thing standing between a dropped connection and a
double spend, which is why the Venue protocol makes adapters choose.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from services.execution.keys import LEG_FOR_KIND, REASON_FOR_KIND, client_order_id
from services.execution.venue import Fill, VenueRejected, VenueUnknown
from services.trade_plan import bracket, notional_usd

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Outcome:
    status: str
    detail: Dict[str, Any]


def _iso(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def signal_index(candles: Sequence[Dict[str, Any]], signal_bar_time: datetime) -> Optional[int]:
    """
    Where the signal's bar sits in the candles we can see now.

    None when it has fallen out of the window, which is not an error: it means this
    intent is older than the tape it was priced against, and a fill now would be a
    different trade.
    """
    wanted = int(signal_bar_time.timestamp() * 1000)
    for i in range(len(candles) - 1, -1, -1):
        if int(candles[i]["time"]) == wanted:
            return i
    return None


def size_entry(
    intent: Dict[str, Any],
    candles: Sequence[Dict[str, Any]],
    *,
    equity_usd: float,
    caps: Sequence[float],
) -> Optional[Dict[str, Any]]:
    """
    The trade this intent becomes, in dollars, or None if there is no room for one.

    The bracket comes from services/trade_plan, the same function the backtester
    calls, so the stop is in the same place the report measured it. The size comes
    from the same clamped fraction, which matters more than it looks: asking for 1%
    of risk against a 0.6% stop takes 0.6%, and an executor doing its own
    arithmetic here would take more risk than what was tested.
    """
    from models.backtest_schemas import ExitPlan

    reference = intent["reference"] or {}
    plan = ExitPlan(**(intent["plan"] or {}))
    index = signal_index(candles, _iso(reference["signal_bar_time"]))
    if index is None or index + 1 >= len(candles):
        return None
    reference_open = float(candles[index + 1]["open"])
    b = bracket(plan, candles, index, reference_open, 1)
    if b is None:
        return None

    notional = notional_usd(b.notional, equity_usd, caps)
    if notional <= 0:
        return None
    return {
        "reference_open": reference_open,
        "entry": b.entry,
        "dist": b.dist,
        "stop": b.stop,
        "target": b.target,
        "fraction": b.notional,
        "notional_usd": notional,
        "risk_usd": notional * (b.dist / b.entry),
        "caps_applied": [c for c in caps if c is not None],
    }


def realised(position: Dict[str, Any], fill: Fill) -> Dict[str, float]:
    """
    What the trade actually did, in dollars and in R.

    R is the profit over the risk taken in dollars, which is the same quantity the
    report calls r - so a live trade and a backtested one can be put side by side
    without converting anything.
    """
    entry = float(position["entry_price"] or 0)
    qty = float(position["qty"] or 0)
    notional = float(position["notional_usd"] or 0)
    stop = float(position["stop_price"] or 0)
    direction = int(position["direction"])
    gross = direction * (fill.price - entry) * qty
    pnl = gross - fill.fee_usd - fill.gas_usd
    dist = abs(entry - stop)
    risk = notional * (dist / entry) if entry and notional else 0.0
    return {
        "pnl_usd": pnl,
        "risk_usd": risk,
        "realised_r": (pnl / risk) if risk > 0 else 0.0,
        "exit_price": fill.price,
    }


class IntentRunner:
    """
    Turns one claimed intent into one venue write.

    Repositories and the venue factory are injected: the tests drive this against a
    fake venue that can reject, hang, or land-and-lose-the-response, which is the
    case the whole ordering above exists for.
    """

    def __init__(self, *, intents, orders, fills, positions, audit, accounts, candles, venue_for):
        self.intents = intents
        self.orders = orders
        self.fills = fills
        self.positions = positions
        self.audit = audit
        self.accounts = accounts
        self.candles = candles
        self.venue_for = venue_for

    async def run(self, intent: Dict[str, Any], *, now: Optional[datetime] = None) -> Outcome:
        now = now or datetime.now(timezone.utc)
        intent_id = str(intent["id"])
        owner = intent["owner_key"]
        kind = intent["kind"]

        account = await self.accounts.get(owner)
        if account is None:
            await self.intents.finish(intent_id, "cancelled", "no execution account")
            return Outcome("cancelled", {"reason": "no execution account"})

        if kind == "entry":
            return await self._entry(intent, account, now)
        return await self._exit(intent, account, now)

    # --- entry ----------------------------------------------------------------

    async def _entry(self, intent: Dict[str, Any], account: Dict[str, Any], now: datetime) -> Outcome:
        intent_id = str(intent["id"])
        owner = intent["owner_key"]
        reference = intent["reference"] or {}

        if _iso(intent["not_after"]) is not None and now > _iso(intent["not_after"]):
            # Abandoned rather than chased. A fill priced off a bar that closed forty
            # minutes ago is a different trade from the one the rule asked for.
            await self.intents.finish(intent_id, "expired", "too late to be the same trade")
            await self._log(owner, "executor", "entry expired", intent_id=intent_id)
            return Outcome("expired", {"reason": "not_after passed"})

        bars = await self.candles.get_candles(reference["symbol"], reference["timeframe"], 40)
        # The rule's ceiling and the account's, smallest first. Both are real and
        # neither may be the one that gets applied by accident.
        rule_cap = float(reference.get("max_notional_usd") or 0) or None
        caps = [c for c in (rule_cap, float(account["max_notional_usd"])) if c]

        venue = self.venue_for(intent, account, None)
        equity = await venue.balance()
        sizing = size_entry(intent, bars, equity_usd=equity, caps=caps)
        if sizing is None:
            await self.intents.finish(intent_id, "expired", "no room to trade")
            await self._log(owner, "executor", "no room to trade", intent_id=intent_id)
            return Outcome("expired", {"reason": "no room"})
        await self.intents.set_sizing(intent_id, sizing)

        coid = client_order_id(intent_id, "entry")
        order = await self.orders.submit(
            owner_key=owner,
            intent_id=intent_id,
            position_id=None,
            client_order_id=coid,
            leg="entry",
            kind="market",
            side="buy",
            qty=None,
            request={"notional_usd": sizing["notional_usd"], "stop": sizing["stop"],
                     "target": sizing["target"], "deadline": _deadline(intent).isoformat()},
        )
        if order is None:
            # This exact write was already sent once. We do not know how it ended,
            # so this is reconciliation's question, not a retry.
            await self.intents.finish(intent_id, "needs_reconcile", "order already submitted")
            return Outcome("needs_reconcile", {"client_order_id": coid})

        try:
            fill = await venue.open(
                notional_usd=sizing["notional_usd"],
                stop_price=sizing["stop"],
                target_price=sizing["target"],
                deadline=_deadline(intent),
                min_out=None,  # the venue knows its own floor; ours would only disagree
                client_order_id=coid,
            )
        except VenueRejected as exc:
            return await self._rejected(intent, order, exc, now)
        except VenueUnknown as exc:
            return await self._unknown(intent, order, exc)

        await self.orders.ack(order["id"], "filled", fill.venue_fill_id, fill.raw)
        # Recorded before the position exists, so an entry fill is never lost to a
        # failure between the two. It is also what the cost measurement reads.
        await self.fills.record(
            owner_key=owner, order_id=order["id"], position_id=None, venue=intent["venue"],
            venue_fill_id=fill.venue_fill_id, price=fill.price, qty=fill.qty,
            fee_usd=fill.fee_usd, gas_usd=fill.gas_usd, filled_at=fill.at,
            raw=fill.raw or {}, tx_ref=fill.tx_ref,
        )
        position = await self.positions.create(
            owner_key=owner,
            rule_id=str(intent["rule_id"]),
            venue=intent["venue"],
            market=intent["market"],
            symbol=reference["symbol"],
            timeframe=reference["timeframe"],
            direction=1,
            status="open",
            mode=intent["mode"],
            entry_intent_id=intent_id,
            entry_event_id=intent.get("event_id"),
            plan=intent["plan"],
            parity_version=intent["parity_version"],
            signal_bar_time=_iso(reference["signal_bar_time"]),
            entry_bar_time=fill.at,
            entry_price=fill.price,
            qty=fill.qty,
            notional_usd=sizing["notional_usd"],
            stop_price=sizing["stop"],
            target_price=sizing["target"],
            deadline_bar_time=_deadline(intent),
            triggers_placed=True,  # the vault stores them in the same transaction
            reference={**sizing, "entry_drift_bps": _drift(sizing["reference_open"], fill.price)},
        )
        if position is None:
            # The unique index refused: this rule already has a live position. The
            # swap happened, so this is not something to paper over.
            await self.intents.finish(intent_id, "needs_reconcile", "a live position already exists")
            await self._log(owner, "executor", "filled into an existing position", intent_id=intent_id)
            return Outcome("needs_reconcile", {"reason": "duplicate position"})

        await self.intents.finish(intent_id, "filled")
        await self._log(
            owner, "executor", "opened", intent_id=intent_id, position_id=str(position["id"]),
            to_status="open",
            detail={"price": fill.price, "qty": fill.qty, "notional_usd": sizing["notional_usd"],
                    "entry_drift_bps": _drift(sizing["reference_open"], fill.price)},
        )
        return Outcome("filled", {"position_id": str(position["id"]), "price": fill.price})

    # --- exit -----------------------------------------------------------------

    async def _exit(self, intent: Dict[str, Any], account: Dict[str, Any], now: datetime) -> Outcome:
        intent_id = str(intent["id"])
        owner = intent["owner_key"]
        position = await self.positions.get(str(intent["position_id"]))
        if position is None or position["status"] == "closed":
            await self.intents.finish(intent_id, "cancelled", "position already closed")
            return Outcome("cancelled", {"reason": "already closed"})

        leg = LEG_FOR_KIND[intent["kind"]]
        reason = REASON_FOR_KIND[intent["kind"]]
        coid = client_order_id(intent_id, leg)
        await self.positions.mark_closing(str(position["id"]))

        order = await self.orders.submit(
            owner_key=owner,
            intent_id=intent_id,
            position_id=str(position["id"]),
            client_order_id=coid,
            leg=leg,
            kind="market",
            side="sell",
            qty=float(position["qty"] or 0),
            request={"reason": reason, "qty": float(position["qty"] or 0)},
            reduce_only=True,
        )
        if order is None:
            await self.intents.finish(intent_id, "needs_reconcile", "exit already submitted")
            return Outcome("needs_reconcile", {"client_order_id": coid})

        venue = self.venue_for(intent, account, position)
        try:
            fill = await venue.close(reason=reason, client_order_id=coid)
        except VenueRejected as exc:
            # The venue disagreed that this exit is allowed - most often its oracle
            # has not crossed the level ours did. Back on the queue: the condition
            # is either true a moment later or the position outlives it.
            return await self._rejected(intent, order, exc, now)
        except VenueUnknown as exc:
            return await self._unknown(intent, order, exc)

        await self.orders.ack(order["id"], "filled", fill.venue_fill_id, fill.raw)
        await self.fills.record(
            owner_key=owner, order_id=order["id"], position_id=str(position["id"]),
            venue=intent["venue"], venue_fill_id=fill.venue_fill_id, price=fill.price,
            qty=fill.qty, fee_usd=fill.fee_usd, gas_usd=fill.gas_usd, filled_at=fill.at,
            raw=fill.raw or {}, tx_ref=fill.tx_ref,
        )
        numbers = realised(position, fill)
        await self.positions.close(
            str(position["id"]),
            exit_price=numbers["exit_price"],
            exit_reason=reason,
            realised_pnl_usd=numbers["pnl_usd"],
            realised_r=numbers["realised_r"],
            reference={**(position["reference"] or {}), "exit": numbers, "trigger": reason},
        )
        await self.intents.finish(intent_id, "filled")
        await self._log(
            owner, "executor", f"closed: {reason}", intent_id=intent_id,
            position_id=str(position["id"]), to_status="closed", detail=numbers,
        )
        return Outcome("filled", {"position_id": str(position["id"]), **numbers})

    # --- failure paths --------------------------------------------------------

    async def _rejected(self, intent, order, exc: Exception, now: datetime) -> Outcome:
        intent_id = str(intent["id"])
        await self.orders.ack(order["id"], "rejected", None, None, str(exc)[:300])
        attempts = int(intent.get("attempts") or 1)
        expired = _iso(intent["not_after"]) is not None and now > _iso(intent["not_after"])
        if attempts < MAX_ATTEMPTS and not expired:
            # Safe, because VenueRejected is a promise that nothing happened.
            await self.intents.requeue(intent_id, str(exc)[:300])
            return Outcome("queued", {"attempts": attempts, "error": str(exc)[:300]})
        await self.intents.finish(intent_id, "rejected", str(exc)[:300])
        await self._log(intent["owner_key"], "executor", "rejected", intent_id=intent_id,
                        detail={"error": str(exc)[:300], "attempts": attempts})
        return Outcome("rejected", {"attempts": attempts})

    async def _unknown(self, intent, order, exc: Exception) -> Outcome:
        """
        The one path that must never retry. We do not know whether the swap
        happened, and finding out is reconciliation's job; guessing here is how an
        account ends up with two positions or pays twice.
        """
        intent_id = str(intent["id"])
        await self.orders.ack(order["id"], "unknown", None, None, str(exc)[:300])
        await self.intents.finish(intent_id, "needs_reconcile", str(exc)[:300])
        await self._log(intent["owner_key"], "executor", "outcome unknown", intent_id=intent_id,
                        detail={"error": str(exc)[:300]})
        return Outcome("needs_reconcile", {"error": str(exc)[:300]})

    async def _log(self, owner, actor, reason, **kw) -> None:
        await self.audit.record(owner_key=owner, actor=actor, reason=reason, **kw)


def _deadline(intent: Dict[str, Any]) -> datetime:
    """
    When this position runs out of bars, as a clock time.

    Stored rather than counted, so the time exit needs no market data at all -
    which is what makes it the exit that still works when candles are unavailable.
    """
    from services.history_service import TIMEFRAME_MS
    from datetime import timedelta

    reference = intent["reference"] or {}
    plan = intent["plan"] or {}
    step = TIMEFRAME_MS.get(reference.get("timeframe"), 3_600_000)
    max_bars = int(plan.get("max_bars") or 20)
    entry_open = _iso(reference["reference_open_time"])
    return entry_open + timedelta(milliseconds=step * max_bars)


def _drift(reference: float, got: float) -> float:
    """How far the fill landed from the price the report would have used, in bps."""
    return round((got - reference) / reference * 10_000, 2) if reference else 0.0
