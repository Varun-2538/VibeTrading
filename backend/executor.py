"""
The execution process.

A third container, not a thread in the API and not a job in the backtest worker.

Not the API, because the alert sweep runs there: `rule_engine.fire` awaits the
action inline, so one slow RPC would delay every other wallet's alerts, and with
`coalesce=True` a multi-minute stall does not merely arrive late - the bars that
closed during it are never evaluated by anyone, and the fires are gone. The API also
restarts on every deploy, and a trade has to survive a deploy.

Not the backtest worker, because that container is deliberately starved:
`cpu_shares: 256`, `mem_limit: 512m`, and a replay that saturates a core for up to an
hour. An exit that must land within seconds of a bar close cannot queue behind one,
and being OOM-killed mid-trade by our own replay would be the worst coupling in the
system.

Three loops, each with its own clock:

    promote   every 2s   queued fires become intents
    intents   every 2s   one claim, one venue write
    monitor   every 10s  open positions, and the exits nobody else can see
    reconcile every 300s and once at boot, before anything else runs

The boot reconcile is a gate, not a courtesy: the loops refuse to start until it has
finished, because sending a new write while an old one's outcome is unknown is how an
account spends twice.
"""
import asyncio
import os
import signal
import socket
import time
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from models.database import db
from repositories.rule_repository import RuleEventRepository
from repositories.execution_repository import (
    ExecutionAccountRepository,
    ExecutionAuditRepository,
    ExecutionFillRepository,
    ExecutionIntentRepository,
    ExecutionOrderRepository,
    ExecutionPolicyRepository,
    ExecutionPositionRepository,
    ExecutionSettingsRepository,
)
from services.candle_service import CandleService, close_http
from services.execution.monitor import PositionMonitor
from services.execution.reconcile import Reconciler
from services.execution.registry import venue_for
from services.execution.runner import IntentRunner
from services.execution.promote import promote_queued_events

HEARTBEAT = "/tmp/executor-heartbeat"
INTENT_POLL_SECONDS = 2
MONITOR_SECONDS = 10
RECONCILE_SECONDS = 300
# Shorter than the backtester's, deliberately: a dead executor holding open positions
# has to be noticed inside a bar, not inside three minutes.
HEARTBEAT_SECONDS = 30

EXECUTOR_ID = os.environ.get("EXECUTOR_ID") or f"executor@{socket.gethostname()}"


def enabled() -> bool:
    """
    The environment switch, which survives a database outage and needs a restart to
    change. The row in execution_settings is the one that can be flipped live. Either
    being off means off, and both ship off.
    """
    return os.environ.get("EXECUTION_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def beat() -> None:
    with open(HEARTBEAT, "w", encoding="utf-8") as handle:
        handle.write(str(time.time()))


def build_runner() -> IntentRunner:
    return IntentRunner(
        intents=ExecutionIntentRepository,
        orders=ExecutionOrderRepository,
        fills=ExecutionFillRepository,
        positions=ExecutionPositionRepository,
        audit=ExecutionAuditRepository,
        accounts=ExecutionAccountRepository,
        candles=CandleService,
        venue_for=venue_for,
    )


def build_monitor() -> PositionMonitor:
    return PositionMonitor(
        positions=ExecutionPositionRepository,
        intents=ExecutionIntentRepository,
        accounts=ExecutionAccountRepository,
        settings=ExecutionSettingsRepository,
        audit=ExecutionAuditRepository,
        candles=CandleService,
        venue_for=venue_for,
    )


def build_reconciler() -> Reconciler:
    return Reconciler(
        intents=ExecutionIntentRepository,
        orders=ExecutionOrderRepository,
        fills=ExecutionFillRepository,
        positions=ExecutionPositionRepository,
        accounts=ExecutionAccountRepository,
        audit=ExecutionAuditRepository,
        venue_for=venue_for,
    )


async def promote_once() -> int:
    return await promote_queued_events(
        intents=ExecutionIntentRepository,
        fires=RuleEventRepository,
        policies=ExecutionPolicyRepository,
        audit=ExecutionAuditRepository,
    )


async def intent_loop(stop: asyncio.Event, ready: asyncio.Event) -> None:
    runner = build_runner()
    await ready.wait()
    while not stop.is_set():
        try:
            await promote_once()
            intent = await ExecutionIntentRepository.claim(EXECUTOR_ID)
            if intent is None:
                await asyncio.sleep(INTENT_POLL_SECONDS)
                continue
            print(f"[executor] {intent['kind']} {intent['id']} claimed", flush=True)
            outcome = await runner.run(intent)
            print(f"[executor] {intent['id']} -> {outcome.status}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad intent must not end the loop
            print(f"[executor] intent loop error: {exc}", flush=True)
            await asyncio.sleep(INTENT_POLL_SECONDS)


async def monitor_loop(stop: asyncio.Event, ready: asyncio.Event) -> None:
    monitor = build_monitor()
    await ready.wait()
    while not stop.is_set():
        try:
            taken = await monitor.tick()
            for decision in taken:
                print(f"[executor] monitor queued {decision.kind} ({decision.reason})", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[executor] monitor error: {exc}", flush=True)
        await asyncio.sleep(MONITOR_SECONDS)


async def reconcile_loop(stop: asyncio.Event, ready: asyncio.Event) -> None:
    reconciler = build_reconciler()
    # The boot pass gates everything else: nothing new may be sent while an old
    # write's outcome is unknown.
    try:
        report = await reconciler.run()
        print(f"[executor] reconciled at boot: {report.as_dict()}", flush=True)
    except Exception as exc:  # noqa: BLE001
        # Refusing to start is the right failure here. The alternative is trading
        # with books we know might be wrong.
        print(f"[executor] boot reconcile failed, not starting loops: {exc}", flush=True)
        return
    ready.set()

    while not stop.is_set():
        await asyncio.sleep(RECONCILE_SECONDS)
        if stop.is_set():
            break
        try:
            report = await reconciler.run()
            if report.resolved or report.halted:
                print(f"[executor] reconciled: {report.as_dict()}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[executor] reconcile error: {exc}", flush=True)


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(beat, IntervalTrigger(seconds=HEARTBEAT_SECONDS), id="heartbeat", replace_existing=True)
    return scheduler


async def main() -> None:
    await db.connect()
    try:
        await db.bootstrap_schema()
    except Exception as exc:  # noqa: BLE001
        print(f"[executor] schema bootstrap skipped: {exc}", flush=True)

    beat()
    if not enabled():
        # Still running, still beating, still holding nothing: the container stays
        # healthy and does nothing, which is what an unarmed switch should look like.
        print("[executor] EXECUTION_ENABLED is not set; idling", flush=True)
    print(f"[executor] {EXECUTOR_ID} up", flush=True)

    scheduler = build_scheduler()
    scheduler.start()

    stop = asyncio.Event()
    ready = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows development machines
            pass

    tasks = []
    if enabled():
        tasks = [
            asyncio.create_task(reconcile_loop(stop, ready)),
            asyncio.create_task(intent_loop(stop, ready)),
            asyncio.create_task(monitor_loop(stop, ready)),
        ]
    await stop.wait()
    for task in tasks:
        task.cancel()

    scheduler.shutdown(wait=False)
    await close_http()
    await db.disconnect()
    print("[executor] stopped", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
