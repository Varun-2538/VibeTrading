"""
Watching an open position between fires.

A stop is not an alert. The rule engine wakes once a minute to ask "has a setup
appeared"; a position needs a different question, asked more often: "is it time to
be out". This is that loop.

With a vault, most of the danger is already gone. The stop, the target and the
deadline were written into the contract in the same transaction that opened the
position, and anyone can push them - so if this process dies, the exits still
happen, just more slowly and by a stranger collecting a bounty. What this loop adds
is being *first*, and the two exits the chain cannot verify on its own: a kill
switch, and an opposing signal.

`decide` is pure so the whole decision table can be tested without a database, a
clock or a network. The check order is `backtest/trades.py::_exit`'s order, and it
is load-bearing: a bar that touches both the stop and the target is a stop there, so
it must be a stop here.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from services.trade_plan import bar_exit

# How far back to re-read closed bars when deciding. The loop keeps no cursor on
# purpose - a cursor is state that can be wrong across a restart - so it re-reads a
# few bars and stops at the first hit, which is idempotent and cheap.
LOOKBACK_BARS = 6


@dataclass(frozen=True)
class Decision:
    kind: str  # exit_stop | exit_target | exit_time | flatten
    reason: str
    detail: Dict[str, Any]


def closed_bars_since(
    candles: Sequence[Dict[str, Any]], after: Optional[datetime], limit: int = LOOKBACK_BARS
) -> List[Dict[str, Any]]:
    """
    The closed bars worth looking at: after the entry, and not the forming one.

    The last bar from CandleService is still forming, and acting on a forming bar is
    how a backtest and a live account start disagreeing - the whole engine fires on
    closed bars only.
    """
    if len(candles) < 2:
        return []
    closed = candles[:-1]
    if after is not None:
        cut = int(after.timestamp() * 1000)
        closed = [c for c in closed if int(c["time"]) >= cut]
    return list(closed[-limit:])


def decide(
    position: Dict[str, Any],
    *,
    candles: Sequence[Dict[str, Any]],
    quote: Optional[float],
    now: datetime,
    halted: bool,
) -> Optional[Decision]:
    direction = int(position["direction"])
    stop = float(position["stop_price"])
    target = float(position["target_price"]) if position["target_price"] else None

    # 1. A halt beats everything, including a target about to print. If the owner
    #    or reconciliation has said stop, the position comes off.
    if halted:
        return Decision("flatten", "halted", {"trigger": "halt"})

    # 2. The clock, before anything that needs market data - so an outage at the
    #    data provider cannot leave a position unmanaged forever.
    deadline = position["deadline_bar_time"]
    if deadline is not None and now >= deadline:
        return Decision("exit_time", "time", {"trigger": "deadline", "deadline": deadline.isoformat()})

    # 3. The stop, against the live price rather than only the last close. This is a
    #    deliberate departure from the report, which models the stop filling at the
    #    stop when a bar's low reaches it: waiting for the close would leave the
    #    position exposed for the rest of the bar. Capital protection wins, and the
    #    difference is recorded on the position so the parity gap is measurable
    #    rather than invisible.
    if quote is not None:
        if (direction == 1 and quote <= stop) or (direction == -1 and quote >= stop):
            return Decision("exit_stop", "stop", {"trigger": "quote", "price": quote, "stop": stop})

    # 4. Then the bars, through the same function the backtester uses, so
    #    first-hit-wins and a gap through the stop mean the same thing in both.
    for bar in closed_bars_since(candles, position.get("entry_bar_time")):
        hit = bar_exit(
            float(bar["open"]), float(bar["high"]), float(bar["low"]),
            direction, stop, target, first_bar=False,
        )
        if hit is None:
            continue
        price, why = hit
        kind = "exit_stop" if why == "stop" else "exit_target"
        return Decision(kind, why, {"trigger": "bar", "bar_time": int(bar["time"]), "price": price})

    return None


class PositionMonitor:
    """
    One pass over every live position. Injected repositories, so the decision table
    can be driven against a fake venue and scripted candles.
    """

    def __init__(self, *, positions, intents, accounts, settings, audit, candles, venue_for, quote=True):
        self.positions = positions
        self.intents = intents
        self.accounts = accounts
        self.settings = settings
        self.audit = audit
        self.candles = candles
        self.venue_for = venue_for
        self.use_quote = quote

    async def tick(self, *, now: Optional[datetime] = None) -> List[Decision]:
        now = now or datetime.now(timezone.utc)
        globals_ = await self.settings.get()
        taken: List[Decision] = []

        for position in await self.positions.live():
            account = await self.accounts.get(position["owner_key"])
            halted = bool(
                globals_.get("halted_reason")
                or (account and (account["kill_switch"] or account["halted_reason"]))
            )
            bars = await self.candles.get_candles(position["symbol"], position["timeframe"], LOOKBACK_BARS + 3)
            quote = None
            if self.use_quote:
                try:
                    venue = self.venue_for(None, account, position)
                    quote = (await venue.quote()).price
                except Exception:  # noqa: BLE001 - a missing quote is not a reason to stop
                    quote = float(bars[-1]["close"]) if bars else None

            decision = decide(position, candles=bars, quote=quote, now=now, halted=halted)
            if decision is None:
                continue
            queued = await self.intents.queue_exit(
                owner_key=position["owner_key"],
                rule_id=str(position["rule_id"]),
                position_id=str(position["id"]),
                kind=decision.kind,
                mode=position["mode"],
                venue=position["venue"],
                market=position["market"],
                side="sell",
                plan=position["plan"],
                reference={**(position["reference"] or {}), **decision.detail,
                           "symbol": position["symbol"], "timeframe": position["timeframe"],
                           "reference_open_time": now.isoformat()},
                parity_version=position["parity_version"],
                # An exit is worth attempting for far longer than an entry: a late
                # entry is a different trade, a late exit is still the exit.
                not_after=now + timedelta(days=2),
            )
            if queued is None:
                continue  # already queued; the unique index said so
            taken.append(decision)
            await self.audit.record(
                owner_key=position["owner_key"], actor="monitor", reason=f"queued {decision.kind}",
                position_id=str(position["id"]), intent_id=str(queued["id"]), detail=decision.detail,
            )
        return taken
