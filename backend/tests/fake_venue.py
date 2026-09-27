"""
A venue that can fail in every way a real one can, including the one that matters.

Beside walks.py rather than in a test file, matching precedent: it is a fixture, not
a test. The failure injection is the point - especially
`landed_but_lost_the_response()`, where the venue accepts the write *and* raises
VenueUnknown. That is the exact shape of a dropped connection after a swap went
through, and it is what client_order_id and reconciliation exist for.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.execution.venue import Fill, Quote, VenuePosition, VenueRejected, VenueUnknown


class FakeVenue:
    def __init__(self, price: float = 2000.0, *, fee_pct: float = 0.05, gas_usd: float = 0.3):
        self.price = price
        self.fee_pct = fee_pct
        self.gas_usd = gas_usd
        self.equity = 1000.0

        self.opens: List[Dict[str, Any]] = []
        self.closes: List[Dict[str, Any]] = []
        self.seen_ids: List[str] = []
        self._position: Optional[VenuePosition] = None

        self._reject = 0
        self._unknown = 0
        self._land_and_lose = False
        self.refuse_duplicate_client_order_id = True

    # --- failure injection ----------------------------------------------------

    def reject_next(self, n: int = 1) -> None:
        self._reject = n

    def unknown_next(self, n: int = 1) -> None:
        self._unknown = n

    def landed_but_lost_the_response(self) -> None:
        """
        The swap happens and the answer never arrives. A retry here would open a
        second position, so nothing may be retried until someone asks the venue what
        is true.
        """
        self._land_and_lose = True

    # --- reads ----------------------------------------------------------------

    async def quote(self) -> Quote:
        return Quote(price=self.price, at=datetime.now(timezone.utc))

    async def balance(self) -> float:
        return self.equity

    async def position(self) -> VenuePosition:
        return self._position or VenuePosition(open=False)

    # --- writes ---------------------------------------------------------------

    async def open(
        self,
        *,
        notional_usd: float,
        stop_price: float,
        target_price: Optional[float],
        deadline: datetime,
        min_out: Optional[float],
        client_order_id: str,
    ) -> Fill:
        self._guard(client_order_id)
        qty = notional_usd / self.price
        record = {"notional_usd": notional_usd, "stop": stop_price, "target": target_price,
                  "deadline": deadline, "client_order_id": client_order_id}
        if self._land_and_lose:
            self._land_and_lose = False
            self.opens.append(record)
            self._position = VenuePosition(
                open=True, qty=qty, entry_price=self.price, stop_price=stop_price,
                target_price=target_price, deadline=deadline,
            )
            raise VenueUnknown("connection dropped after the swap went through")
        self._maybe_fail()
        self.opens.append(record)
        self._position = VenuePosition(
            open=True, qty=qty, entry_price=self.price, stop_price=stop_price,
            target_price=target_price, deadline=deadline,
        )
        return self._fill(client_order_id, qty, notional_usd)

    async def close(self, *, reason: str, client_order_id: str) -> Fill:
        self._guard(client_order_id)
        if self._land_and_lose:
            self._land_and_lose = False
            self.closes.append({"reason": reason, "client_order_id": client_order_id})
            self._position = VenuePosition(open=False)
            raise VenueUnknown("connection dropped after the swap went through")
        self._maybe_fail()
        if self._position is None or not self._position.open:
            raise VenueRejected("nothing open to close")
        qty = self._position.qty
        self.closes.append({"reason": reason, "client_order_id": client_order_id})
        self._position = VenuePosition(open=False)
        return self._fill(client_order_id, qty, qty * self.price)

    # --- helpers --------------------------------------------------------------

    def _guard(self, client_order_id: str) -> None:
        if self.refuse_duplicate_client_order_id and client_order_id in self.seen_ids:
            raise VenueRejected(f"duplicate client order id {client_order_id}")
        self.seen_ids.append(client_order_id)

    def _maybe_fail(self) -> None:
        if self._reject > 0:
            self._reject -= 1
            raise VenueRejected("the vault refused")
        if self._unknown > 0:
            self._unknown -= 1
            raise VenueUnknown("timed out waiting for a receipt")

    def _fill(self, client_order_id: str, qty: float, notional: float) -> Fill:
        return Fill(
            venue_fill_id="fake:" + client_order_id[:16],
            price=self.price,
            qty=qty,
            fee_usd=notional * self.fee_pct / 100,
            gas_usd=self.gas_usd,
            at=datetime.now(timezone.utc),
            tx_ref="0x" + client_order_id[:8],
            raw={"fake": True},
        )

    def set_open(self, *, qty: float, entry: float, stop: float, target: Optional[float] = None,
                 deadline: Optional[datetime] = None) -> None:
        """Pretend a position exists, for reconciliation tests."""
        self._position = VenuePosition(
            open=True, qty=qty, entry_price=entry, stop_price=stop, target_price=target,
            deadline=deadline or datetime.now(timezone.utc) + timedelta(days=1),
        )

    def set_flat(self) -> None:
        self._position = VenuePosition(open=False)
