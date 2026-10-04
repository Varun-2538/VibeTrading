"""
Watching an open position between fires.

`decide` is pure, so the whole table can be driven without a clock or a database.
The check order matters as much as the checks: a halt beats a printing target, and
the clock is asked before anything that needs market data, so a data outage cannot
leave a position unmanaged.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_execution import (
    FakeAccounts,
    FakeAudit,
    FakeCandles,
    FakeIntents,
    FakePositions,
    FakeSettings,
    bars_at,
)
from fake_venue import FakeVenue
from models.backtest_schemas import ExitPlan
from services.execution.monitor import PositionMonitor, closed_bars_since, decide

H = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % H)
NOW = datetime.fromtimestamp((T0 + 30 * H) / 1000, tz=timezone.utc)
PLAN = ExitPlan(stop_atr=1.5, target_r=2.0, max_bars=20).model_dump()


def position(**over):
    row = {
        "id": "99999999-9999-9999-9999-999999999999",
        "owner_key": "0xabc",
        "rule_id": "11111111-1111-1111-1111-111111111111",
        "venue": "uniswap_v3_arbitrum",
        "market": "WETH/USDC",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "direction": 1,
        "status": "open",
        "mode": "shadow",
        "plan": dict(PLAN),
        "parity_version": 1,
        "entry_price": 2000.0,
        "qty": 0.05,
        "notional_usd": 100.0,
        "stop_price": 1900.0,
        "target_price": 2200.0,
        "entry_bar_time": datetime.fromtimestamp((T0 + 21 * H) / 1000, tz=timezone.utc),
        "deadline_bar_time": datetime.fromtimestamp((T0 + 41 * H) / 1000, tz=timezone.utc),
        "reference": {},
    }
    row.update(over)
    return row


def quiet(n: int = 8, price: float = 2000.0, spread: float = 5.0):
    return bars_at(price, n, start_ms=T0 + 22 * H, step_ms=H, spread=spread)


class TestDecide:
    def test_a_quiet_position_is_left_alone(self):
        assert decide(position(), candles=quiet(), quote=2000.0, now=NOW, halted=False) is None

    def test_a_halt_beats_everything_including_a_printing_target(self):
        bars = quiet()
        bars[-2] = {**bars[-2], "high": 2300.0}  # the target, on a closed bar
        d = decide(position(), candles=bars, quote=2300.0, now=NOW, halted=True)
        assert d.kind == "flatten" and d.reason == "halted"

    def test_the_clock_is_asked_before_anything_needing_market_data(self):
        """
        A position past its deadline comes off even with no candles at all, which is
        what makes the time exit the one that survives a data outage.
        """
        late = NOW + timedelta(days=5)
        d = decide(position(), candles=[], quote=None, now=late, halted=False)
        assert d.kind == "exit_time" and d.detail["trigger"] == "deadline"

    def test_the_stop_fires_on_the_live_price_not_only_the_close(self):
        """
        A deliberate departure from the report, which models the stop filling at the
        stop when a bar's low reaches it. Waiting for the close would leave the
        position exposed for the rest of the bar; the trigger is recorded so the
        difference is measurable rather than invisible.
        """
        d = decide(position(), candles=quiet(), quote=1850.0, now=NOW, halted=False)
        assert d.kind == "exit_stop" and d.detail["trigger"] == "quote"
        assert d.detail["price"] == 1850.0

    def test_a_closed_bar_through_the_stop_still_counts(self):
        bars = quiet()
        bars[-2] = {**bars[-2], "low": 1800.0}
        d = decide(position(), candles=bars, quote=2000.0, now=NOW, halted=False)
        assert d.kind == "exit_stop" and d.detail["trigger"] == "bar"

    def test_a_bar_touching_both_is_a_stop_here_too(self):
        bars = quiet()
        bars[-2] = {**bars[-2], "low": 1800.0, "high": 2300.0}
        d = decide(position(), candles=bars, quote=2000.0, now=NOW, halted=False)
        assert d.kind == "exit_stop"

    def test_a_target_needs_a_closed_bar(self):
        """
        Being slow to take profit costs opportunity; firing a target on a wick costs
        parity with the report. So the target is close-based and the stop is not.
        """
        assert decide(position(), candles=quiet(), quote=2300.0, now=NOW, halted=False) is None
        bars = quiet()
        bars[-2] = {**bars[-2], "high": 2300.0}
        d = decide(position(), candles=bars, quote=2000.0, now=NOW, halted=False)
        assert d.kind == "exit_target"

    def test_the_forming_bar_is_never_acted_on(self):
        """The engine fires on closed bars; a monitor that did otherwise would drift."""
        bars = quiet()
        bars[-1] = {**bars[-1], "low": 1800.0}  # still forming
        assert decide(position(), candles=bars, quote=2000.0, now=NOW, halted=False) is None

    def test_bars_before_the_entry_are_not_reconsidered(self):
        early = bars_at(2000.0, 4, start_ms=T0, step_ms=H)
        early[0] = {**early[0], "low": 1000.0}
        assert closed_bars_since(early + quiet(), position()["entry_bar_time"])[0]["time"] >= T0 + 21 * H


class TestTick:
    async def build(self, *, position_row=None, halted=False, kill=False, quote=2000.0, bars=None):
        positions = FakePositions()
        row = position_row or position()
        positions.rows[row["id"]] = row
        venue = FakeVenue(price=quote)
        monitor = PositionMonitor(
            positions=positions,
            intents=FakeIntents(),
            accounts=FakeAccounts(kill_switch=kill),
            settings=FakeSettings(halted_reason="operator brake" if halted else None),
            audit=FakeAudit(),
            candles=FakeCandles(bars or quiet()),
            venue_for=lambda *a, **k: venue,
        )
        return monitor, positions, row

    async def test_a_triggered_stop_is_queued_once(self):
        monitor, positions, row = await self.build(quote=1850.0)
        first = await monitor.tick(now=NOW)
        assert [d.kind for d in first] == ["exit_stop"]
        # The unique index refuses the second one, so a tick that runs twice across a
        # restart cannot queue two exits.
        assert await monitor.tick(now=NOW) == []
        assert len(monitor.intents.rows) == 1

    async def test_the_kill_switch_flattens(self):
        monitor, _, _ = await self.build(kill=True)
        assert [d.kind for d in await monitor.tick(now=NOW)] == ["flatten"]

    async def test_a_global_halt_flattens_too(self):
        monitor, _, _ = await self.build(halted=True)
        assert [d.kind for d in await monitor.tick(now=NOW)] == ["flatten"]

    async def test_the_queued_exit_carries_the_positions_own_plan(self):
        monitor, _, row = await self.build(quote=1850.0)
        await monitor.tick(now=NOW)
        intent = list(monitor.intents.rows.values())[0]
        assert intent["kind"] == "exit_stop" and intent["position_id"] == row["id"]
        assert intent["plan"] == row["plan"] and intent["mode"] == "shadow"
        # An exit is worth attempting far longer than an entry: a late entry is a
        # different trade, a late exit is still the exit.
        assert intent["not_after"] > NOW + timedelta(days=1)

    async def test_nothing_is_queued_for_a_quiet_position(self):
        monitor, _, _ = await self.build()
        assert await monitor.tick(now=NOW) == []
        assert monitor.intents.rows == {}
