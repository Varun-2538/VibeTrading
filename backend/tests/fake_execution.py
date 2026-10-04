"""
In-memory stand-ins for the execution tables.

They honour the **uniqueness constraints**, not just the shapes. That is the whole
reason they are worth having: the guarantee against double spending lives in five
indexes, so a fake that happily inserted a second live position would let every test
pass while the real system was broken in the one way that matters.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

LIVE = ("opening", "open", "closing")


def uid() -> str:
    return str(uuid.uuid4())


class FakeIntents:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []

    async def queued_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        promoted = {r["event_id"] for r in self.rows.values() if r.get("event_id")}
        return [e for e in self.events if e["event_id"] not in promoted][:limit]

    async def queue_from_event(self, **kw: Any) -> Optional[Dict[str, Any]]:
        # UNIQUE (event_id): one intent per fire, ever.
        if any(r.get("event_id") == kw["event_id"] for r in self.rows.values()):
            return None
        return self._insert(kw)

    async def queue_exit(self, **kw: Any) -> Optional[Dict[str, Any]]:
        # UNIQUE (position_id, kind) for exits: a tick that runs twice cannot queue
        # two flattens.
        if any(
            r.get("position_id") == kw["position_id"] and r["kind"] == kw["kind"]
            for r in self.rows.values()
        ):
            return None
        return self._insert(kw)

    def _insert(self, kw: Dict[str, Any]) -> Dict[str, Any]:
        row = {
            "id": uid(), "status": "queued", "attempts": 0, "claimed_at": None,
            "claimed_by": None, "finished_at": None, "error": None, "sizing": None,
            "event_id": None, "position_id": None,
            "created_at": datetime.now(timezone.utc),
            **kw,
        }
        self.rows[row["id"]] = row
        return dict(row)

    async def get(self, intent_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(str(intent_id))
        return dict(row) if row else None

    async def claim(self, claimed_by: str) -> Optional[Dict[str, Any]]:
        """Exits before entries, oldest first - the real ORDER BY."""
        queued = [r for r in self.rows.values() if r["status"] == "queued"]
        queued.sort(key=lambda r: (r["kind"] == "entry", r["created_at"]))
        if not queued:
            return None
        row = queued[0]
        row.update(status="claimed", claimed_by=claimed_by, attempts=row["attempts"] + 1,
                   claimed_at=datetime.now(timezone.utc))
        return dict(row)

    async def finish(self, intent_id: str, status: str, error: Optional[str] = None) -> None:
        row = self.rows[str(intent_id)]
        row.update(status=status, error=error, finished_at=datetime.now(timezone.utc))

    async def requeue(self, intent_id: str, error: Optional[str] = None) -> None:
        row = self.rows[str(intent_id)]
        row.update(status="queued", error=error, claimed_at=None, claimed_by=None)

    async def set_sizing(self, intent_id: str, sizing: Dict[str, Any]) -> None:
        self.rows[str(intent_id)]["sizing"] = sizing

    async def stuck(self, older_than_seconds: int = 300) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.rows.values() if r["status"] in ("claimed", "submitting")]

    def status_of(self, intent_id: str) -> str:
        return self.rows[str(intent_id)]["status"]


class FakePositions:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    async def open_for_rule(self, owner_key: str, rule_id: str, mode: str) -> Optional[Dict[str, Any]]:
        for row in self.rows.values():
            if (row["owner_key"], str(row["rule_id"]), row["mode"]) == (owner_key, str(rule_id), mode) \
                    and row["status"] in LIVE:
                return dict(row)
        return None

    async def create(self, **kw: Any) -> Optional[Dict[str, Any]]:
        # The unique partial index: one live position per rule, per venue, per mode.
        if await self.open_for_rule(kw["owner_key"], str(kw["rule_id"]), kw["mode"]):
            return None
        row = {
            "id": uid(), "status": kw.get("status", "open"), "exit_price": None,
            "exit_reason": None, "closed_at": None, "realised_pnl_usd": None,
            "realised_r": None, "reconciled_at": None,
            "opened_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
            "triggers_placed": kw.get("triggers_placed", True), "reference": kw.get("reference"),
            **kw,
        }
        self.rows[row["id"]] = row
        return dict(row)

    async def get(self, position_id: str, owner_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = self.rows.get(str(position_id))
        if row is None or (owner_key and row["owner_key"] != owner_key):
            return None
        return dict(row)

    async def live(self, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.rows.values()
                if r["status"] in LIVE and (mode is None or r["mode"] == mode)]

    async def mark_closing(self, position_id: str) -> bool:
        row = self.rows.get(str(position_id))
        if row is None or row["status"] not in ("opening", "open"):
            return False
        row["status"] = "closing"
        return True

    async def close(self, position_id: str, **kw: Any) -> Optional[Dict[str, Any]]:
        row = self.rows[str(position_id)]
        if row["status"] == "closed":
            return None
        row.update(status="closed", closed_at=datetime.now(timezone.utc),
                   exit_price=kw["exit_price"], exit_reason=kw["exit_reason"],
                   realised_pnl_usd=kw["realised_pnl_usd"], realised_r=kw["realised_r"],
                   reference=kw.get("reference") or row.get("reference"))
        return dict(row)

    async def abandon(self, position_id: str, reason: str) -> None:
        row = self.rows[str(position_id)]
        row.update(status="abandoned", exit_reason="reconciled", closed_at=datetime.now(timezone.utc))

    async def closed_count(self, owner_key: str, mode: str) -> int:
        return sum(1 for r in self.rows.values()
                   if r["owner_key"] == owner_key and r["mode"] == mode and r["status"] == "closed")


class FakeOrders:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self._ids = itertools.count(1)

    async def submit(self, **kw: Any) -> Optional[Dict[str, Any]]:
        # UNIQUE (client_order_id): the retry refusing itself.
        if any(r["client_order_id"] == kw["client_order_id"] for r in self.rows):
            return None
        row = {"id": next(self._ids), "status": "submitting", "venue_order_id": None,
               "response": None, "error": None, "acked_at": None,
               "submitted_at": datetime.now(timezone.utc), **kw}
        self.rows.append(row)
        return dict(row)

    async def ack(self, order_id: int, status: str, venue_order_id=None, response=None, error=None) -> None:
        for row in self.rows:
            if row["id"] == order_id:
                row.update(status=status, venue_order_id=venue_order_id, response=response,
                           error=error, acked_at=datetime.now(timezone.utc))

    async def in_doubt(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.rows if r["status"] in ("submitting", "unknown")]

    async def for_intent(self, intent_id: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.rows if str(r["intent_id"]) == str(intent_id)]

    def count(self) -> int:
        return len(self.rows)


class FakeFills:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self._ids = itertools.count(1)

    async def record(self, **kw: Any) -> Optional[Dict[str, Any]]:
        # UNIQUE (venue, venue_fill_id): a replayed poll cannot book a fill twice.
        key = (kw["venue"], kw["venue_fill_id"])
        if any((r["venue"], r["venue_fill_id"]) == key for r in self.rows):
            return None
        row = {"id": next(self._ids), **kw}
        self.rows.append(row)
        return dict(row)

    async def for_position(self, position_id: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.rows if str(r.get("position_id")) == str(position_id)]


class FakeAudit:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    async def record(self, **kw: Any) -> None:
        self.rows.append(kw)

    async def for_position(self, position_id: str) -> List[Dict[str, Any]]:
        return [r for r in self.rows if str(r.get("position_id")) == str(position_id)]

    def reasons(self) -> List[str]:
        return [r["reason"] for r in self.rows]


class FakeAccounts:
    def __init__(self, **over: Any) -> None:
        self.row = {
            "owner_key": "0xabc", "mode": "shadow", "kill_switch": False, "equity_usd": 1000.0,
            "max_notional_usd": 200.0, "max_concurrent_positions": 1, "max_trades_per_day": 5,
            "daily_loss_limit_usd": 25.0, "halted_reason": None, "halted_at": None,
        }
        self.row.update(over)
        self.halts: List[str] = []

    async def get(self, owner_key: str) -> Optional[Dict[str, Any]]:
        return dict(self.row) if owner_key == self.row["owner_key"] else None

    async def halt(self, owner_key: str, reason: str) -> Optional[Dict[str, Any]]:
        self.halts.append(reason)
        self.row["halted_reason"] = reason
        return dict(self.row)

    async def set_kill_switch(self, owner_key: str, on: bool) -> Optional[Dict[str, Any]]:
        self.row["kill_switch"] = on
        return dict(self.row)


class FakeSettings:
    def __init__(self, enabled: bool = True, halted_reason: Optional[str] = None) -> None:
        self.row = {"enabled": enabled, "halted_reason": halted_reason, "updated_at": None}

    async def get(self) -> Dict[str, Any]:
        return dict(self.row)


class FakePolicies:
    def __init__(self, row: Optional[Dict[str, Any]] = None) -> None:
        self.row = row

    async def get(self, rule_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        return dict(self.row) if self.row else None


class FakeCandles:
    """CandleService's one method, over a fixed series."""

    def __init__(self, bars: List[Dict[str, Any]]) -> None:
        self.bars = bars
        self.calls: List[Any] = []

    async def get_candles(self, symbol: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        self.calls.append((symbol, timeframe, limit))
        return self.bars[-limit:]


def bars_at(price: float, n: int, *, start_ms: int, step_ms: int, spread: float = 1.0) -> List[Dict[str, Any]]:
    return [
        {"time": start_ms + i * step_ms, "open": price, "high": price + spread,
         "low": price - spread, "close": price, "volume": 1.0}
        for i in range(n)
    ]
