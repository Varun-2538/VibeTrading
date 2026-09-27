"""
One intent, one venue write, and every way that can go wrong.

The crash matrix is the reason this file exists. A trade that is sent twice is worse
than a trade that is never sent, so the tests that matter are the ones where the
process learns nothing about what happened.
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
    FakeFills,
    FakeIntents,
    FakeOrders,
    FakePositions,
    bars_at,
)
from fake_venue import FakeVenue
from models.backtest_schemas import ExitPlan
from services.execution.keys import client_order_id
from services.execution.runner import IntentRunner, realised, size_entry
from services.trade_plan import PARITY_VERSION

H = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % H)
SIGNAL_BAR = datetime.fromtimestamp((T0 + 20 * H) / 1000, tz=timezone.utc)
OWNER = "0xabc"
RULE = "11111111-1111-1111-1111-111111111111"

PLAN = ExitPlan(stop_atr=1.5, target_r=2.0, max_bars=20, fee_pct=0.05, slippage_pct=0.02).model_dump()


def series(n: int = 40, price: float = 2000.0, spread: float = 20.0):
    return bars_at(price, n, start_ms=T0, step_ms=H, spread=spread)


def intent(**over):
    reference = {
        "signal_bar_time": datetime.fromtimestamp((T0 + 20 * H) / 1000, tz=timezone.utc).isoformat(),
        "reference_open_time": datetime.fromtimestamp((T0 + 21 * H) / 1000, tz=timezone.utc).isoformat(),
        "signal_price": 2000.0,
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "max_notional_usd": 100.0,
    }
    reference.update(over.pop("reference", {}))
    row = {
        "id": "22222222-2222-2222-2222-222222222222",
        "owner_key": OWNER,
        "rule_id": RULE,
        "event_id": 7,
        "position_id": None,
        "kind": "entry",
        "status": "claimed",
        "mode": "shadow",
        "venue": "uniswap_v3_arbitrum",
        "market": "WETH/USDC",
        "side": "buy",
        "plan": dict(PLAN),
        "reference": reference,
        "sizing": None,
        "parity_version": PARITY_VERSION,
        "not_after": datetime.now(timezone.utc) + timedelta(minutes=5),
        "attempts": 1,
    }
    row.update(over)
    return row


def build(venue=None, *, candles=None, accounts=None):
    venue = venue or FakeVenue()
    repos = {
        "intents": FakeIntents(),
        "orders": FakeOrders(),
        "fills": FakeFills(),
        "positions": FakePositions(),
        "audit": FakeAudit(),
        "accounts": accounts or FakeAccounts(),
        "candles": candles or FakeCandles(series()),
    }
    runner = IntentRunner(venue_for=lambda *a, **k: venue, **repos)
    return runner, venue, repos


async def claimed(runner, repos, row):
    """Put the intent in the fake table the way a claim would have."""
    repos["intents"].rows[row["id"]] = dict(row)
    return await runner.run(row)


class TestSizing:
    def test_the_bracket_comes_from_the_shared_maths(self):
        sizing = size_entry(intent(), series(), equity_usd=1000.0, caps=[100.0])
        # A 1.5-ATR stop on a series whose bars are 40 wide: the stop is below entry
        # and the target is twice as far above it.
        assert sizing["stop"] < sizing["entry"] < sizing["target"]
        assert sizing["notional_usd"] == 100.0  # the rule's cap, not the equity
        assert sizing["risk_usd"] == pytest.approx(100.0 * sizing["dist"] / sizing["entry"])

    def test_the_smallest_cap_wins(self):
        assert size_entry(intent(), series(), equity_usd=1000.0, caps=[500.0, 60.0])["notional_usd"] == 60.0

    def test_a_signal_bar_that_has_fallen_out_of_the_window_is_no_trade(self):
        """An intent older than the tape it was priced against cannot be sized."""
        assert size_entry(intent(), series()[-3:], equity_usd=1000.0, caps=[100.0]) is None

    def test_a_flat_series_has_no_room(self):
        assert size_entry(intent(), series(spread=0.0), equity_usd=1000.0, caps=[100.0]) is None


class TestEntry:
    async def test_a_clean_entry_books_an_order_a_fill_and_a_position(self):
        runner, venue, repos = build()
        row = intent()
        outcome = await claimed(runner, repos, row)

        assert outcome.status == "filled"
        assert repos["orders"].count() == 1
        assert repos["orders"].rows[0]["status"] == "filled"
        assert repos["orders"].rows[0]["client_order_id"] == client_order_id(row["id"], "entry")
        assert len(repos["fills"].rows) == 1
        position = (await repos["positions"].live())[0]
        assert position["status"] == "open" and position["direction"] == 1
        # The vault writes the stop in the same transaction as the swap, so there is
        # no window where a position exists without one.
        assert position["triggers_placed"] is True
        assert position["stop_price"] < position["entry_price"]
        assert repos["intents"].status_of(row["id"]) == "filled"

    async def test_the_order_row_exists_before_the_venue_is_called(self):
        """
        A rejection proves it: the row is there, with the failure recorded on it,
        even though nothing was ever filled.
        """
        runner, venue, repos = build()
        venue.reject_next()
        row = intent()
        await claimed(runner, repos, row)
        assert repos["orders"].count() == 1
        assert repos["orders"].rows[0]["status"] == "rejected"
        assert "refused" in repos["orders"].rows[0]["error"]

    async def test_a_rejection_goes_back_on_the_queue_while_there_is_time(self):
        runner, venue, repos = build()
        venue.reject_next()
        row = intent(attempts=1)
        outcome = await claimed(runner, repos, row)
        assert outcome.status == "queued"
        assert repos["intents"].status_of(row["id"]) == "queued"

    async def test_a_rejection_stops_after_three_attempts(self):
        runner, venue, repos = build()
        venue.reject_next()
        row = intent(attempts=3)
        outcome = await claimed(runner, repos, row)
        assert outcome.status == "rejected"
        assert repos["intents"].status_of(row["id"]) == "rejected"

    async def test_an_unknown_outcome_is_never_retried(self):
        """
        The single most important test in the file. A timeout means we do not know
        whether the swap happened, and a retry would be how an account ends up with
        two positions.
        """
        runner, venue, repos = build()
        venue.unknown_next()
        row = intent()
        outcome = await claimed(runner, repos, row)
        assert outcome.status == "needs_reconcile"
        assert repos["intents"].status_of(row["id"]) == "needs_reconcile"
        assert repos["orders"].rows[0]["status"] == "unknown"
        assert await repos["positions"].live() == []

    async def test_a_write_that_landed_and_lost_its_answer_leaves_exactly_one_order(self):
        runner, venue, repos = build()
        venue.landed_but_lost_the_response()
        row = intent()
        outcome = await claimed(runner, repos, row)

        assert outcome.status == "needs_reconcile"
        # One order row, one position on the venue, nothing in our books yet: exactly
        # the state reconciliation is written to resolve.
        assert repos["orders"].count() == 1
        assert (await venue.position()).open is True
        assert await repos["positions"].live() == []

    async def test_the_same_intent_run_twice_sends_one_write(self):
        runner, venue, repos = build()
        row = intent()
        await claimed(runner, repos, row)
        again = await runner.run(dict(row))
        assert again.status == "needs_reconcile"
        assert repos["orders"].count() == 1
        assert len(venue.opens) == 1

    async def test_an_expired_intent_is_abandoned_rather_than_chased(self):
        runner, venue, repos = build()
        row = intent(not_after=datetime.now(timezone.utc) - timedelta(seconds=1))
        outcome = await claimed(runner, repos, row)
        assert outcome.status == "expired"
        assert repos["orders"].count() == 0 and venue.opens == []

    async def test_filling_into_an_existing_position_halts_rather_than_hides(self):
        runner, venue, repos = build()
        await repos["positions"].create(
            owner_key=OWNER, rule_id=RULE, venue="uniswap_v3_arbitrum", market="WETH/USDC",
            symbol="ETHUSDT", timeframe="1h", direction=1, mode="shadow",
            entry_intent_id="other", plan=PLAN, parity_version=PARITY_VERSION,
            signal_bar_time=SIGNAL_BAR, stop_price=1900.0, deadline_bar_time=SIGNAL_BAR,
        )
        row = intent()
        outcome = await claimed(runner, repos, row)
        # The swap happened; the unique index refused the second position. That is not
        # something to paper over.
        assert outcome.status == "needs_reconcile"
        assert len(venue.opens) == 1

    async def test_an_account_that_does_not_exist_cancels(self):
        runner, venue, repos = build(accounts=FakeAccounts(owner_key="0xsomeone-else"))
        outcome = await claimed(runner, repos, intent())
        assert outcome.status == "cancelled"


class TestExit:
    async def open_one(self):
        runner, venue, repos = build()
        await claimed(runner, repos, intent())
        position = (await repos["positions"].live())[0]
        return runner, venue, repos, position

    async def test_an_exit_closes_the_position_and_books_the_numbers(self):
        runner, venue, repos, position = await self.open_one()
        venue.price = 2100.0  # a winner
        row = intent(id="33333333-3333-3333-3333-333333333333", kind="exit_target",
                     position_id=position["id"], event_id=None, side="sell")
        outcome = await claimed(runner, repos, row)

        assert outcome.status == "filled"
        closed = await repos["positions"].get(position["id"])
        assert closed["status"] == "closed" and closed["exit_reason"] == "target"
        assert closed["realised_pnl_usd"] > 0 and closed["realised_r"] > 0
        assert venue.closes[-1]["reason"] == "target"

    async def test_an_exit_on_an_already_closed_position_is_cancelled(self):
        runner, venue, repos, position = await self.open_one()
        await repos["positions"].close(position["id"], exit_price=2000.0, exit_reason="stop",
                                       realised_pnl_usd=-1.0, realised_r=-1.0)
        row = intent(id="44444444-4444-4444-4444-444444444444", kind="exit_stop",
                     position_id=position["id"], event_id=None)
        assert (await claimed(runner, repos, row)).status == "cancelled"

    async def test_a_venue_that_refuses_the_exit_leaves_it_queued(self):
        """
        Most often its oracle has not crossed the level ours did. The position is
        still there, so trying again in a moment is right - and an exit only ever
        reduces exposure, so there is nothing unsafe about the retry.
        """
        runner, venue, repos, position = await self.open_one()
        venue.reject_next()
        row = intent(id="55555555-5555-5555-5555-555555555555", kind="exit_stop",
                     position_id=position["id"], event_id=None, attempts=1)
        outcome = await claimed(runner, repos, row)
        assert outcome.status == "queued"
        assert (await repos["positions"].get(position["id"]))["status"] == "closing"

    async def test_an_exit_whose_answer_was_lost_waits_for_reconciliation(self):
        runner, venue, repos, position = await self.open_one()
        venue.landed_but_lost_the_response()
        row = intent(id="66666666-6666-6666-6666-666666666666", kind="exit_stop",
                     position_id=position["id"], event_id=None)
        outcome = await claimed(runner, repos, row)
        assert outcome.status == "needs_reconcile"
        assert (await venue.position()).open is False  # it did close, we just do not know
        assert (await repos["positions"].get(position["id"]))["status"] == "closing"


class TestRealised:
    def test_r_is_profit_over_the_dollars_that_were_at_risk(self):
        from services.execution.venue import Fill

        position = {"entry_price": 2000.0, "qty": 0.05, "notional_usd": 100.0,
                    "stop_price": 1900.0, "direction": 1}
        # A 5% stop on a $100 position risks $5. Exiting at the target, +$10 gross.
        fill = Fill(venue_fill_id="x", price=2200.0, qty=0.05, fee_usd=0.0, gas_usd=0.0,
                    at=datetime.now(timezone.utc))
        numbers = realised(position, fill)
        assert numbers["pnl_usd"] == pytest.approx(10.0)
        assert numbers["risk_usd"] == pytest.approx(5.0)
        assert numbers["realised_r"] == pytest.approx(2.0)

    def test_costs_come_off_the_result_the_way_the_report_charges_them(self):
        from services.execution.venue import Fill

        position = {"entry_price": 2000.0, "qty": 0.05, "notional_usd": 100.0,
                    "stop_price": 1900.0, "direction": 1}
        fill = Fill(venue_fill_id="x", price=2200.0, qty=0.05, fee_usd=0.05, gas_usd=0.30,
                    at=datetime.now(timezone.utc))
        assert realised(position, fill)["pnl_usd"] == pytest.approx(10.0 - 0.35)
