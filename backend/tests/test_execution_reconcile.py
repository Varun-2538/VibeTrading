"""
Making the books agree with the chain before anything new is sent.

Every row of the state-match table, and two that matter more than the rest: an
unexplained position **halts and never flattens**, because a reconciliation bug that
flattens turns a display error into a realised loss; and an entry whose answer was
lost is only requeued when the venue says it never landed.
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
    FakeFills,
    FakeIntents,
    FakeOrders,
    FakePositions,
)
from fake_venue import FakeVenue
from models.backtest_schemas import ExitPlan
from services.execution.keys import client_order_id
from services.execution.reconcile import Reconciler

OWNER = "0xabc"
RULE = "11111111-1111-1111-1111-111111111111"
PLAN = ExitPlan(stop_atr=1.5, target_r=2.0, max_bars=20).model_dump()
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def build(venue=None):
    venue = venue or FakeVenue()
    repos = {
        "intents": FakeIntents(),
        "orders": FakeOrders(),
        "fills": FakeFills(),
        "positions": FakePositions(),
        "accounts": FakeAccounts(),
        "audit": FakeAudit(),
    }
    return Reconciler(venue_for=lambda *a, **k: venue, **repos), venue, repos


async def an_intent(repos, kind="entry", position_id=None, not_after=None):
    row = await repos["intents"].queue_from_event(
        owner_key=OWNER, rule_id=RULE, event_id=len(repos["intents"].rows) + 1, kind=kind,
        mode="shadow", venue="uniswap_v3_arbitrum", market="WETH/USDC", side="buy",
        plan=dict(PLAN), reference={"symbol": "ETHUSDT", "timeframe": "1h"},
        parity_version=1, not_after=not_after or NOW + timedelta(minutes=5),
        position_id=position_id,
    )
    await repos["intents"].finish(row["id"], "needs_reconcile", "timed out")
    return row


async def a_position(repos, **over):
    return await repos["positions"].create(
        owner_key=OWNER, rule_id=RULE, venue="uniswap_v3_arbitrum", market="WETH/USDC",
        symbol="ETHUSDT", timeframe="1h", direction=1, mode="shadow",
        entry_intent_id="x", plan=dict(PLAN), parity_version=1,
        signal_bar_time=NOW - timedelta(hours=2), entry_bar_time=NOW - timedelta(hours=1),
        entry_price=2000.0, qty=0.05, notional_usd=100.0, stop_price=1900.0,
        target_price=2200.0, deadline_bar_time=NOW + timedelta(days=1), **over,
    )


async def an_order(repos, intent_id, leg="entry", position_id=None):
    return await repos["orders"].submit(
        owner_key=OWNER, intent_id=intent_id, position_id=position_id,
        client_order_id=client_order_id(intent_id, leg), leg=leg, kind="market",
        side="buy" if leg == "entry" else "sell", qty=None, request={},
    )


class TestEntryInDoubt:
    async def test_an_entry_that_never_landed_goes_back_on_the_queue(self):
        reconciler, venue, repos = build()
        intent = await an_intent(repos)
        await an_order(repos, intent["id"])
        venue.set_flat()

        report = await reconciler.run(now=NOW)
        assert repos["intents"].status_of(intent["id"]) == "queued"
        assert repos["orders"].rows[0]["status"] == "rejected"
        assert any("requeued" in r for r in report.resolved)

    async def test_but_not_if_it_is_too_late_to_be_the_same_trade(self):
        reconciler, venue, repos = build()
        intent = await an_intent(repos, not_after=NOW - timedelta(minutes=1))
        await an_order(repos, intent["id"])
        venue.set_flat()

        await reconciler.run(now=NOW)
        assert repos["intents"].status_of(intent["id"]) == "expired"

    async def test_an_entry_that_landed_but_was_never_booked_halts_the_account(self):
        """
        The dangerous one. There is a position on the chain that our books do not
        know about, and no amount of arithmetic here can safely invent it.
        """
        reconciler, venue, repos = build()
        intent = await an_intent(repos)
        await an_order(repos, intent["id"])
        venue.set_open(qty=0.05, entry=2000.0, stop=1900.0)

        report = await reconciler.run(now=NOW)
        assert repos["accounts"].halts == ["an entry landed that we did not book"]
        assert OWNER in report.halted
        assert repos["intents"].status_of(intent["id"]) == "needs_reconcile"
        # And nothing was closed, flattened or guessed at.
        assert venue.closes == []


class TestExitInDoubt:
    async def test_an_exit_that_never_landed_is_retried(self):
        reconciler, venue, repos = build()
        position = await a_position(repos)
        intent = await an_intent(repos, kind="exit_stop", position_id=position["id"])
        await an_order(repos, intent["id"], leg="stop", position_id=position["id"])
        venue.set_open(qty=0.05, entry=2000.0, stop=1900.0)

        await reconciler.run(now=NOW)
        # Safe: an exit only ever reduces exposure, and the position is still there.
        assert repos["intents"].status_of(intent["id"]) == "queued"

    async def test_an_exit_that_landed_closes_the_books_from_the_fill(self):
        reconciler, venue, repos = build()
        position = await a_position(repos)
        intent = await an_intent(repos, kind="exit_stop", position_id=position["id"])
        order = await an_order(repos, intent["id"], leg="stop", position_id=position["id"])
        await repos["fills"].record(
            owner_key=OWNER, order_id=order["id"], position_id=position["id"],
            venue="uniswap_v3_arbitrum", venue_fill_id="f1", price=1890.0, qty=0.05,
            fee_usd=0.05, gas_usd=0.3, filled_at=NOW, raw={},
        )
        venue.set_flat()

        await reconciler.run(now=NOW)
        closed = await repos["positions"].get(position["id"])
        assert closed["status"] == "closed" and closed["exit_reason"] == "reconciled"
        assert closed["exit_price"] == 1890.0
        assert closed["realised_r"] < 0  # it was a stop
        assert repos["intents"].status_of(intent["id"]) == "filled"


class TestPositionsAgainstVenue:
    async def test_a_position_closed_out_of_band_is_written_up(self):
        """
        A stranger took the bounty, or the vault's own trigger fired. Not a problem -
        it is the design working - but the books have to catch up.
        """
        reconciler, venue, repos = build()
        position = await a_position(repos)
        await repos["fills"].record(
            owner_key=OWNER, order_id=1, position_id=position["id"],
            venue="uniswap_v3_arbitrum", venue_fill_id="f2", price=1885.0, qty=0.05,
            fee_usd=0.05, gas_usd=0.3, filled_at=NOW, raw={"by": "a stranger"},
        )
        venue.set_flat()

        report = await reconciler.run(now=NOW)
        closed = await repos["positions"].get(position["id"])
        assert closed["status"] == "closed" and closed["exit_price"] == 1885.0
        assert repos["accounts"].halts == []  # nothing unexplained happened
        assert any("closed" in r for r in report.resolved)

    async def test_a_position_with_no_fill_to_read_is_abandoned_not_invented(self):
        reconciler, venue, repos = build()
        position = await a_position(repos)
        venue.set_flat()

        report = await reconciler.run(now=NOW)
        row = await repos["positions"].get(position["id"])
        assert row["status"] == "abandoned"
        assert any("no fill" in note for note in report.notes)

    async def test_an_agreed_open_position_is_left_alone(self):
        reconciler, venue, repos = build()
        position = await a_position(repos)
        venue.set_open(qty=0.05, entry=2000.0, stop=1900.0)

        await reconciler.run(now=NOW)
        assert (await repos["positions"].get(position["id"]))["status"] == "open"
        assert venue.closes == []

    async def test_a_venue_that_cannot_be_reached_changes_nothing(self):
        class Unreachable(FakeVenue):
            async def position(self):
                from services.execution.venue import VenueUnknown

                raise VenueUnknown("no node")

        reconciler, venue, repos = build(Unreachable())
        position = await a_position(repos)
        report = await reconciler.run(now=NOW)
        assert (await repos["positions"].get(position["id"]))["status"] == "open"
        assert report.notes and repos["accounts"].halts == []
