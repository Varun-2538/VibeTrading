"""
A venue that records what would have been sent, and sends nothing.

A wrapper rather than an `if` inside the executor, and the distinction matters: the
reads are real, so sizing, the oracle floor and every trigger decision see live
prices, and the *same code path* runs that a live account runs. There is no
live-only branch that shadow has never exercised.

What it buys, beyond safety: a real parity measurement at zero spend. A week in
shadow says what this strategy actually costs against what the report modelled,
which is the one number no backtest can produce for itself.

Costs are charged from the plan rather than observed, because there is nothing to
observe: the pool fee the plan assumed, on both swaps, plus its gas. A shadow run
therefore reproduces the report's cost model exactly, and the gap that shows up
later in live is the gap between the model and the chain - which is precisely what
the preflight's cost check is looking for.
"""
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.candle_service import CandleService
from services.execution.venue import Fill, Quote, VenuePosition, VenueRejected

SHADOW_VENUE = "shadow"


class ShadowVenue:
    """
    Reads from the market, writes to nowhere.

    `position_row` is our own row for this rule, because in shadow our database
    *is* the venue - there is nothing else to ask. Reconciliation against a shadow
    venue is therefore always consistent by construction, which is correct: the
    thing it exists to catch cannot happen when no transaction was ever sent.
    """

    def __init__(
        self,
        *,
        symbol: str,
        timeframe: str,
        plan: Dict[str, Any],
        equity_usd: float,
        position_row: Optional[Dict[str, Any]] = None,
        candles=CandleService,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.plan = plan
        self.equity_usd = equity_usd
        self.position_row = position_row
        self._candles = candles

    async def quote(self) -> Quote:
        bars = await self._candles.get_candles(self.symbol, self.timeframe, 3)
        if not bars:
            # Same shape as a venue that cannot be reached: definitely nothing
            # happened, so the caller may retry.
            raise VenueRejected("no candles to price against")
        # The forming bar's close is the best "now" we have, and it is the price a
        # real fill would have happened near.
        return Quote(price=float(bars[-1]["close"]), at=datetime.now(timezone.utc))

    async def balance(self) -> float:
        """
        What the owner declared, since there is no vault to ask. This is the one
        read a shadow account cannot make real, and it is why equity_usd exists.
        """
        return float(self.equity_usd)

    async def position(self) -> VenuePosition:
        row = self.position_row
        if row is None or row["status"] not in ("opening", "open", "closing"):
            return VenuePosition(open=False)
        return VenuePosition(
            open=True,
            qty=float(row["qty"] or 0),
            entry_price=float(row["entry_price"] or 0),
            stop_price=float(row["stop_price"] or 0),
            target_price=float(row["target_price"]) if row["target_price"] else None,
            deadline=row["deadline_bar_time"],
        )

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
        price = (await self.quote()).price
        qty = notional_usd / price if price > 0 else 0.0
        if qty <= 0:
            raise VenueRejected("nothing to buy at that price")
        return self._fill(client_order_id, price, qty, notional_usd)

    async def close(self, *, reason: str, client_order_id: str) -> Fill:
        row = self.position_row
        if row is None:
            raise VenueRejected("no shadow position to close")
        price = (await self.quote()).price
        qty = float(row["qty"] or 0)
        return self._fill(client_order_id, price, qty, qty * price)

    def _fill(self, client_order_id: str, price: float, qty: float, notional: float) -> Fill:
        fee = notional * float(self.plan.get("fee_pct", 0.0)) / 100
        gas = float(self.plan.get("gas_usd", 0.0))
        return Fill(
            # Derived from the client order id, so a shadow fill is as idempotent
            # as a real one: replaying the same write books the same fill.
            venue_fill_id="shadow:" + hashlib.sha256(client_order_id.encode()).hexdigest()[:24],
            price=price,
            qty=qty,
            fee_usd=fee,
            gas_usd=gas,
            at=datetime.now(timezone.utc),
            tx_ref=None,
            raw={"shadow": True, "client_order_id": client_order_id, "notional_usd": notional},
        )
