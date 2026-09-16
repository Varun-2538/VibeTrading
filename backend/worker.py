"""
The backtest worker process.

Runs beside the API in its own container, at a lower CPU share, so nothing it
does can delay a live alert. It keeps candles_history current and runs backtest
jobs one at a time.

    python worker.py
"""
import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backtest.runner import run_job
from models.database import db
from repositories.backtest_repository import BacktestRepository
from services.candle_service import _http, close_http
from services.history_service import BackfillResult, topup_all

HEARTBEAT_PATH = Path("/tmp/worker-heartbeat")
TOPUP_JOB_ID = "history_topup"
EVICT_JOB_ID = "tape_eviction"
POLL_SECONDS = 5


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


def build_scheduler(topup, heartbeat, evict=None) -> AsyncIOScheduler:
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
    if evict is not None:
        scheduler.add_job(
            evict,
            trigger=IntervalTrigger(hours=6),
            id=EVICT_JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    return scheduler


async def _topup() -> None:
    client = await _http()
    print(summarise(await topup_all(client=client)), flush=True)


async def job_loop(stop: asyncio.Event, *, jobs=None, run=None, poll: float = POLL_SECONDS) -> None:
    """
    One job at a time, oldest first. A job still marked running when the worker
    starts was interrupted - there is only one worker - so it goes back on the
    queue and resumes from whatever tape it had finished.
    """
    jobs = jobs or BacktestRepository
    run = run or run_job
    requeued = await jobs.requeue_running()
    if requeued:
        print(f"[backtest] requeued {requeued} interrupted job(s)", flush=True)

    while not stop.is_set():
        job = await jobs.claim_next()
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll)
            except asyncio.TimeoutError:
                pass
            continue
        print(f"[backtest] {job['id']} started", flush=True)
        await run(job)
        print(f"[backtest] {job['id']} ended", flush=True)


async def main() -> None:
    await db.connect()
    await db.bootstrap_schema()
    print("[worker] connected; schema up to date", flush=True)

    scheduler = build_scheduler(_topup, beat, evict=BacktestRepository.evict_tapes)
    scheduler.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows development machines
            pass
    loop_task = asyncio.create_task(job_loop(stop))
    await stop.wait()
    loop_task.cancel()

    scheduler.shutdown(wait=False)
    await close_http()
    await db.disconnect()
    print("[worker] stopped", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
