"""
What the sweep does when an armed rule fires.

Two properties matter more than the rest: it never raises, because `fire()` has
already committed the event by the time it runs; and it does no network I/O, because
it runs inside the 60-second alert sweep where one slow call would delay every other
wallet's alerts and a stall would silently drop the bars that closed during it.

The outcome table mirrors `backtest/trades.py::simulate`. The middle row is the
subtle one: an opposing signal against an open position **closes and does not
reverse**, because `simulate` exits at that signal and counts it as
skipped_in_position rather than entering it. Getting it wrong doubles the live trade
count against the report.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_execution import FakePolicies, FakePositions
from models.backtest_schemas import ExitPlan
from services.actions.dex_trade import DexTradeAction
from services.rule_engine import Signal
from services.trade_plan import PARITY_VERSION

OWNER = "0xabc"
RULE_ID = "11111111-1111-1111-1111-111111111111"
BAR = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def rule():
    return {"id": RULE_ID, "owner_key": OWNER, "symbol": "ETHUSDT", "timeframe": "1h"}


def policy(*, armed=True, parity=None, exit_on_opposite=False, **config):
    plan = ExitPlan(stop_atr=1.5, target_r=2.0, max_bars=20, exit_on_opposite=exit_on_opposite)
    base = {"neutral": "skip", "sides": "long", "max_entry_delay_secs": 120,
            "max_slippage_bps": 50, "max_notional_usd": 100.0}
    base.update(config)
    return {
        "rule_id": RULE_ID, "owner_key": OWNER, "armed": armed,
        "venue": "uniswap_v3_arbitrum", "market": "WETH/USDC",
        "exit_plan": plan.model_dump(), "policy": base,
        "parity_version": PARITY_VERSION if parity is None else parity,
        "backtest_job_id": "job", "preflight": {"passed": True},
    }


def signal(direction="bullish"):
    return Signal(
        rule_id=RULE_ID, agent="sequence", symbol="ETHUSDT", timeframe="1h",
        candle_time=BAR, identity="seq:1", direction=direction, price=2000.0,
        provisional=False, evidence={},
    )


def action(policy_row=None, positions=None):
    return DexTradeAction(policies=FakePolicies(policy_row), positions=positions or FakePositions())


async def existing(positions, direction=1, mode="shadow"):
    return await positions.create(
        owner_key=OWNER, rule_id=RULE_ID, venue="uniswap_v3_arbitrum", market="WETH/USDC",
        symbol="ETHUSDT", timeframe="1h", direction=direction, mode=mode,
        entry_intent_id="x", plan={}, parity_version=PARITY_VERSION, signal_bar_time=BAR,
        stop_price=1900.0, deadline_bar_time=BAR,
    )


async def test_an_armed_rule_queues_an_entry():
    result = await action(policy()).execute(rule(), signal(), 7)
    assert result.status == "queued"
    assert result.result["kind"] == "entry"
    assert result.result["market"] == "WETH/USDC"
    # The bar after the signal's is the bar simulate enters at, and the executor
    # reads that bar's open when it picks this up.
    assert result.result["reference"]["reference_open_time"] == "2026-09-27T13:00:00+00:00"
    assert result.result["not_after"] == "2026-09-27T13:02:00+00:00"
    assert result.result["plan"]["stop_atr"] == 1.5


async def test_a_rule_that_is_not_armed_does_nothing():
    assert (await action(None).execute(rule(), signal(), 7)).status == "skipped"
    unarmed = await action(policy(armed=False)).execute(rule(), signal(), 7)
    assert unarmed.status == "skipped" and "not armed" in unarmed.result["reason"]


async def test_a_policy_armed_under_older_arithmetic_is_refused():
    """
    Refused here as well as at arming, because arming happened in the past and the
    constant may have moved since.
    """
    result = await action(policy(parity=PARITY_VERSION - 1)).execute(rule(), signal(), 7)
    assert result.status == "skipped" and "arithmetic" in result.result["reason"]


async def test_a_second_signal_while_in_position_is_skipped():
    positions = FakePositions()
    await existing(positions)
    result = await action(policy(), positions).execute(rule(), signal(), 7)
    assert result.status == "skipped" and result.result["reason"] == "in_position"


async def test_an_opposing_signal_closes_and_does_not_reverse():
    positions = FakePositions()
    row = await existing(positions)
    result = await action(policy(exit_on_opposite=True), positions).execute(
        rule(), signal("bearish"), 7
    )
    assert result.status == "queued"
    assert result.result["kind"] == "exit_opposite"
    assert result.result["position_id"] == row["id"]


async def test_an_opposing_signal_without_that_setting_is_just_skipped():
    positions = FakePositions()
    await existing(positions)
    result = await action(policy(exit_on_opposite=False), positions).execute(
        rule(), signal("bearish"), 7
    )
    assert result.status == "skipped" and result.result["reason"] == "in_position"


async def test_a_bearish_signal_with_no_position_cannot_be_traded_on_a_pool():
    result = await action(policy()).execute(rule(), signal("bearish"), 7)
    assert result.status == "skipped" and "cannot short" in result.result["reason"]


async def test_a_directionless_signal_follows_the_neutral_setting():
    skipped = await action(policy(neutral="skip")).execute(rule(), signal("neutral"), 7)
    assert skipped.status == "skipped" and "no direction" in skipped.result["reason"]
    read_long = await action(policy(neutral="long")).execute(rule(), signal("neutral"), 7)
    assert read_long.status == "queued"


async def test_it_never_raises_whatever_the_repositories_do():
    """
    fire() has already committed the event by the time this runs, so an exception
    here would lose the delivery status of a fire that really happened.
    """
    class Broken:
        async def get(self, *a, **k):
            raise RuntimeError("the database went away")

    result = await DexTradeAction(policies=Broken(), positions=FakePositions()).execute(
        rule(), signal(), 7
    )
    assert result.status == "failed" and "went away" in result.result["error"]


async def test_it_returns_queued_rather_than_sent():
    """
    'sent' would be a lie: nothing has been sent. The executor moves the row on when
    it picks the fire up, and the status vocabulary has 'queued' for exactly this.
    """
    result = await action(policy()).execute(rule(), signal(), 7)
    assert result.status == "queued"
    assert result.result["state"] == "queued"
