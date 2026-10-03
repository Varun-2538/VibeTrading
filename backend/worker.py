"""
The backtest worker process.

Runs beside the API in its own container, at a lower CPU share, so nothing it
does can delay a live alert. Slice 1 gives it one duty: keep candles_history
current. Later slices add the backtest job loop here.

    python worker.py
"""
import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from models.database import db
from services.candle_service import _http, close_http
from services.history_service import BackfillResult, topup_all

HEARTBEAT_PATH = Path("/tmp/worker-heartbeat")
TOPUP_JOB_ID = "history_topup"


def beat(path: Path = HEARTBEAT_PATH) -> None:
    """Touched every minute; the container healthcheck reads its age."""
    path.touch()


def summarise(results: List[BackfillResult]) -> str:
    bars = sum(r.bars for r in results)
    failures = [f"{r.symbol} {r.timeframe}: {r.error}" for r in results if r.error]
    line = f"[history] {bars} bars across {len(results)} series"
    if failures:
        line += "; failed: " + "; ".join(failures)
    return line


def build_scheduler(topup, heartbeat) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        topup,
        trigger=IntervalTrigger(hours=1),
        id=TOPUP_JOB_ID,
        next_run_time=datetime.now(timezone.utc),
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        heartbeat,
        trigger=IntervalTrigger(seconds=60),
        id="heartbeat",
        next_run_time=datetime.now(timezone.utc),
        replace_existing=True,
    )
    return scheduler


async def _topup() -> None:
    client = await _http()
    print(summarise(await topup_all(client=client)), flush=True)


async def main() -> None:
    await db.connect()
    await db.bootstrap_schema()
    print("[worker] connected; schema up to date", flush=True)

    scheduler = build_scheduler(_topup, beat)
    scheduler.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows development machines
            pass
    await stop.wait()

    scheduler.shutdown(wait=False)
    await close_http()
    await db.disconnect()
    print("[worker] stopped", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
