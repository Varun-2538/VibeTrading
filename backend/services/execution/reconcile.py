"""
Make the database agree with the venue before anything new is sent.

This is where the backtest worker's pattern deliberately does not transfer.
`BacktestRepository.requeue_running()` blindly resets every running job at boot,
which is safe because a replay has no side effects outside its own row. An intent's
side effect is a trade. Resetting a 'submitting' intent without first asking whether
it landed is exactly how an account spends twice.

So: the venue is the authority, every in-doubt write is matched against it by the
position it would have created, and anything that cannot be explained **halts the
account rather than being guessed at**. A reconciliation bug that flattens on a
mismatch turns a display error into a realised loss, so it never flattens.

Exits for known positions keep running while an account is halted. A halt is about
not opening anything new; refusing to close would be a trap.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.execution.runner import realised
from services.execution.venue import VenueError


@dataclass
class ReconcileReport:
    checked: int = 0
    resolved: List[str] = field(default_factory=list)
    halted: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "checked": self.checked,
            "resolved": list(self.resolved),
            "halted": list(self.halted),
            "notes": list(self.notes),
        }


class Reconciler:
    def __init__(self, *, intents, orders, fills, positions, accounts, audit, venue_for):
        self.intents = intents
        self.orders = orders
        self.fills = fills
        self.positions = positions
        self.accounts = accounts
        self.audit = audit
        self.venue_for = venue_for

    async def run(self, *, now: Optional[datetime] = None) -> ReconcileReport:
        now = now or datetime.now(timezone.utc)
        report = ReconcileReport()
        await self._orders_in_doubt(report, now)
        await self._positions_against_venue(report, now)
        return report

    # --- writes whose outcome we never learned --------------------------------

    async def _orders_in_doubt(self, report: ReconcileReport, now: datetime) -> None:
        for order in await self.orders.in_doubt():
            report.checked += 1
            owner = order["owner_key"]
            account = await self.accounts.get(owner)
            position = (
                await self.positions.get(str(order["position_id"])) if order["position_id"] else None
            )
            try:
                venue = self.venue_for(None, account, position)
                on_venue = await venue.position()
            except VenueError as exc:
                report.notes.append(f"{order['client_order_id']}: venue unreachable ({exc})")
                continue

            if order["leg"] == "entry":
                await self._entry_in_doubt(order, on_venue, report, now)
            else:
                await self._exit_in_doubt(order, position, on_venue, report, now)

    async def _entry_in_doubt(self, order, on_venue, report: ReconcileReport, now: datetime) -> None:
        owner = order["owner_key"]
        intent_id = str(order["intent_id"])
        if not on_venue.open:
            # It never landed. The intent may go back on the queue, but only if the
            # trade it was priced for is still the same trade.
            await self.orders.ack(order["id"], "rejected", None, None, "reconciled: never landed")
            intent = await self.intents.get(intent_id)
            if intent and intent["not_after"] and now <= intent["not_after"]:
                await self.intents.requeue(intent_id, "reconciled: never landed")
                report.resolved.append(f"{order['client_order_id']}: requeued")
            else:
                await self.intents.finish(intent_id, "expired", "reconciled: never landed, too late")
                report.resolved.append(f"{order['client_order_id']}: expired")
            await self._log(owner, "entry never landed", intent_id=intent_id)
            return

        # It did land, and we have a position on the venue we may not have booked.
        await self.orders.ack(order["id"], "filled", None, {"reconciled": True})
        await self.intents.finish(intent_id, "needs_reconcile", "reconciled: landed, unbooked")
        await self.accounts.halt(owner, "an entry landed that we did not book")
        report.halted.append(owner)
        await self._log(owner, "entry landed but was never booked", intent_id=intent_id)

    async def _exit_in_doubt(self, order, position, on_venue, report: ReconcileReport, now: datetime) -> None:
        owner = order["owner_key"]
        intent_id = str(order["intent_id"])
        if on_venue.open:
            # The exit did not happen. Safe to try again: an exit only ever reduces
            # exposure, and the position is still there to be closed.
            await self.orders.ack(order["id"], "rejected", None, None, "reconciled: still open")
            await self.intents.requeue(intent_id, "reconciled: still open")
            report.resolved.append(f"{order['client_order_id']}: exit requeued")
            await self._log(owner, "exit never landed", intent_id=intent_id,
                            position_id=str(order["position_id"]) if order["position_id"] else None)
            return

        # The venue is flat, so the position closed - by our order, by a trigger the
        # vault verified, or by a stranger collecting the bounty. All three are the
        # same fact: it is closed, and the books have to say so.
        await self.orders.ack(order["id"], "filled", None, {"reconciled": True})
        await self.intents.finish(intent_id, "filled", "reconciled: venue is flat")
        if position is not None and position["status"] != "closed":
            await self._close_from_venue(position, "reconciled", report)
        report.resolved.append(f"{order['client_order_id']}: closed out of band")

    # --- our rows against the venue's ----------------------------------------

    async def _positions_against_venue(self, report: ReconcileReport, now: datetime) -> None:
        for position in await self.positions.live():
            report.checked += 1
            owner = position["owner_key"]
            account = await self.accounts.get(owner)
            try:
                venue = self.venue_for(None, account, position)
                on_venue = await venue.position()
            except VenueError as exc:
                report.notes.append(f"{position['id']}: venue unreachable ({exc})")
                continue

            if on_venue.open:
                continue  # agreed

            # Closed out of band: a trigger fired, or someone took the bounty. Not a
            # problem - it is the design working - but the books have to catch up.
            await self._close_from_venue(position, "reconciled", report)

    async def _close_from_venue(self, position, reason: str, report: ReconcileReport) -> None:
        """
        Close our row from what the venue's own fills say, never from a guess. If
        there is no fill to read, the row is abandoned rather than given invented
        numbers - a made-up exit price is worse than an admitted gap.
        """
        fills = await self.fills.for_position(str(position["id"]))
        exit_fill = fills[-1] if fills else None
        if exit_fill is None:
            await self.positions.abandon(str(position["id"]), reason)
            await self._log(position["owner_key"], "closed on venue with no fill to read",
                            position_id=str(position["id"]))
            report.notes.append(f"{position['id']}: abandoned, no fill")
            return

        from services.execution.venue import Fill

        fill = Fill(
            venue_fill_id=exit_fill["venue_fill_id"],
            price=float(exit_fill["price"]),
            qty=float(exit_fill["qty"]),
            fee_usd=float(exit_fill["fee_usd"]),
            gas_usd=float(exit_fill["gas_usd"]),
            at=exit_fill["filled_at"],
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
        await self._log(position["owner_key"], f"closed from venue state ({reason})",
                        position_id=str(position["id"]), to_status="closed", detail=numbers)
        report.resolved.append(f"{position['id']}: closed")

    async def _log(self, owner, reason, **kw) -> None:
        await self.audit.record(owner_key=owner, actor="reconcile", reason=reason, **kw)
