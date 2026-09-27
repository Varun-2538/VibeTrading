"""
The executor process: what it refuses to do before it is sure of its own books.

In the shape of test_worker.py - the wiring, the heartbeat, and the one property
that must never regress: the loops do not run until reconciliation has finished. A
bug that skipped that has to fail a test rather than a trade.
"""
import asyncio
import contextlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import executor
from fake_execution import FakeAudit, FakeIntents, FakePolicies
from models.backtest_schemas import ExitPlan
from services.execution.promote import promote_queued_events
from services.trade_plan import PARITY_VERSION

NOW = datetime.now(timezone.utc)


def test_execution_is_off_unless_the_environment_says_otherwise(monkeypatch):
    """
    Two switches, and each fails differently: this one survives a database outage and
    needs a restart, the row in execution_settings can be flipped live. Both ship off.
    """
    monkeypatch.delenv("EXECUTION_ENABLED", raising=False)
    assert executor.enabled() is False
    for value in ("true", "TRUE", "1", "yes"):
        monkeypatch.setenv("EXECUTION_ENABLED", value)
        assert executor.enabled() is True
    monkeypatch.setenv("EXECUTION_ENABLED", "no")
    assert executor.enabled() is False


def test_the_heartbeat_window_is_tighter_than_the_backtesters():
    """
    A dead executor holding open positions has to be noticed inside a bar, not inside
    three minutes.
    """
    import worker

    assert executor.HEARTBEAT_SECONDS < 60
    assert executor.HEARTBEAT != str(worker.HEARTBEAT_PATH)
    assert executor.MONITOR_SECONDS <= 10 and executor.INTENT_POLL_SECONDS <= 5


def test_the_scheduler_only_beats(monkeypatch):
    scheduler = executor.build_scheduler()
    assert [job.id for job in scheduler.get_jobs()] == ["heartbeat"]


def test_the_heartbeat_writes_a_readable_timestamp(tmp_path, monkeypatch):
    path = tmp_path / "beat"
    monkeypatch.setattr(executor, "HEARTBEAT", str(path))
    executor.beat()
    assert float(path.read_text(encoding="utf-8")) > 0


async def test_the_loops_wait_for_reconciliation(monkeypatch):
    """
    The important one. Sending a new write while an old one's outcome is unknown is
    how an account spends twice, so the queue is not touched until the boot pass has
    finished. The gate is an event, and this drives it directly rather than waiting
    on a real reconcile.
    """
    claims: list = []

    class Intents:
        @staticmethod
        async def claim(who):
            claims.append(who)
            return None

    monkeypatch.setattr(executor, "ExecutionIntentRepository", Intents)
    monkeypatch.setattr(executor, "promote_once", _none)
    monkeypatch.setattr(executor, "build_runner", lambda: None)
    monkeypatch.setattr(executor, "INTENT_POLL_SECONDS", 0.01)

    stop, ready = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(executor.intent_loop(stop, ready))
    await asyncio.sleep(0.05)
    assert claims == [], "nothing may be claimed before reconciliation has finished"

    ready.set()
    await asyncio.sleep(0.05)
    stop.set()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert claims, "and once it has, the loop claims"


async def test_a_successful_boot_reconcile_opens_the_gate(monkeypatch):
    class Fine:
        async def run(self, **kw):
            return _Report()

    monkeypatch.setattr(executor, "build_reconciler", lambda: Fine())
    monkeypatch.setattr(executor, "RECONCILE_SECONDS", 0.01)
    stop, ready = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(executor.reconcile_loop(stop, ready))
    await asyncio.wait_for(ready.wait(), timeout=2)
    stop.set()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


class _Report:
    resolved: list = []
    halted: list = []

    def as_dict(self):
        return {}


async def test_a_failed_boot_reconcile_never_sets_ready(monkeypatch):
    """
    Refusing to start is the right failure: the alternative is trading with books we
    already know might be wrong.
    """
    class Broken:
        async def run(self, **kw):
            raise RuntimeError("no node")

    monkeypatch.setattr(executor, "build_reconciler", lambda: Broken())
    stop, ready = asyncio.Event(), asyncio.Event()
    await executor.reconcile_loop(stop, ready)
    assert not ready.is_set()


async def _none(*args, **kwargs):
    return 0


# --- promotion -------------------------------------------------------------------


def policy(armed=True, parity=None):
    return {
        "rule_id": "11111111-1111-1111-1111-111111111111", "owner_key": "0xabc",
        "armed": armed, "venue": "uniswap_v3_arbitrum", "market": "WETH/USDC",
        "exit_plan": ExitPlan(stop_atr=1.5, target_r=2.0, max_bars=20).model_dump(),
        "policy": {"neutral": "skip", "sides": "long"},
        "parity_version": PARITY_VERSION if parity is None else parity,
    }


class Fires:
    """RuleEventRepository's one method that promotion needs."""

    def __init__(self) -> None:
        self.writes: list = []

    async def set_action_result_if(self, event_id, expected, status, result):
        self.writes.append((event_id, tuple(expected), status, result))
        return True


def queued_event(**over):
    result = {
        "state": "queued", "kind": "entry", "event_id": 7,
        "reference": {"symbol": "ETHUSDT", "timeframe": "1h",
                      "signal_bar_time": NOW.isoformat(),
                      "reference_open_time": NOW.isoformat()},
        "not_after": (NOW + timedelta(minutes=5)).isoformat(),
    }
    result.update(over.pop("action_result", {}))
    row = {"event_id": 7, "rule_id": "11111111-1111-1111-1111-111111111111",
           "owner_key": "0xabc", "action_result": result, "fired_at": NOW,
           "account_mode": "shadow"}
    row.update(over)
    return row


async def promote(event, policy_row=policy()):
    intents, fires, audit = FakeIntents(), Fires(), FakeAudit()
    intents.events = [event]
    created = await promote_queued_events(
        intents=intents, fires=fires, policies=FakePolicies(policy_row), audit=audit
    )
    return created, intents, fires


async def test_a_queued_fire_becomes_an_intent():
    created, intents, fires = await promote(queued_event())
    assert created == 1
    intent = list(intents.rows.values())[0]
    assert intent["kind"] == "entry" and intent["mode"] == "shadow"
    assert intent["venue"] == "uniswap_v3_arbitrum"
    assert fires.writes[0][1] == ("queued",)  # moved on only from where we left it


async def test_promoting_twice_creates_one_intent():
    """The unique index on event_id is what makes the loop safe to re-run."""
    intents, fires, audit = FakeIntents(), Fires(), FakeAudit()
    intents.events = [queued_event()]
    kwargs = dict(intents=intents, fires=fires, policies=FakePolicies(policy()), audit=audit)
    assert await promote_queued_events(**kwargs) == 1
    assert await promote_queued_events(**kwargs) == 0
    assert len(intents.rows) == 1


async def test_a_rule_disarmed_since_the_fire_is_not_promoted():
    """A fire is not a licence that outlives the permission that allowed it."""
    created, intents, fires = await promote(queued_event(), policy(armed=False))
    assert created == 0 and intents.rows == {}
    assert fires.writes[0][2] == "skipped"
    assert "no longer armed" in fires.writes[0][3]["reason"]


async def test_an_account_still_switched_off_is_left_alone():
    created, intents, fires = await promote(queued_event(account_mode="off"))
    assert created == 0 and fires.writes == []  # not skipped either; simply not yet


async def test_a_fire_too_old_to_be_the_same_trade_is_recorded_as_such():
    stale = queued_event(action_result={"not_after": (NOW - timedelta(minutes=1)).isoformat()})
    created, intents, fires = await promote(stale)
    assert created == 0
    assert "too late" in fires.writes[0][3]["reason"]
