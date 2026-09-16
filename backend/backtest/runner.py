"""
Run one backtest job end to end.

Load history, replay it into a candidate tape in chunks (or take the cached
tape), turn the tape into fires, study them on seen and unseen bars, write the
report. Between chunks the runner reports progress and checks whether the job
was cancelled or has run too long; the replay itself runs in a thread so the
worker's heartbeat keeps beating.
"""
import asyncio
import time
from typing import Any, Dict, Optional

from backtest.replay import first_index, replay_range, tape_key
from backtest.signals import distinct_setups, signals_from_tape
from backtest.study import study
from models.backtest_schemas import BacktestCreate, required_bars
from services.history_service import TIMEFRAME_MS

CHUNK_BARS = 500
JOB_TIMEOUT_SECONDS = 3600


class JobCancelled(Exception):
    """The owner cancelled the job; leave it as they left it."""


class JobFailed(Exception):
    """A reason safe to show the owner."""


def _repos(jobs, history):
    if jobs is None:
        from repositories.backtest_repository import BacktestRepository

        jobs = BacktestRepository
    if history is None:
        from repositories.history_repository import HistoryRepository

        history = HistoryRepository
    return jobs, history


async def run_job(
    job: Dict[str, Any],
    *,
    jobs: Any = None,
    history: Any = None,
    clock=time.monotonic,
    chunk: int = CHUNK_BARS,
    to_thread=asyncio.to_thread,
) -> Optional[Dict[str, Any]]:
    jobs, history = _repos(jobs, history)
    started = clock()
    try:
        report = await _run(job, jobs, history, clock, started, chunk, to_thread)
    except JobCancelled:
        return None
    except Exception as exc:  # noqa: BLE001 - every failure must land on the job
        await jobs.fail(job["id"], str(exc)[:500] or exc.__class__.__name__)
        return None
    await jobs.finish(job["id"], report)
    return report


async def _checkpoint(job, jobs, status, progress, clock, started) -> None:
    if await jobs.status_of(job["id"]) == "cancelled":
        raise JobCancelled()
    if clock() - started > JOB_TIMEOUT_SECONDS:
        raise JobFailed("timeout: the backtest ran for more than an hour")
    await jobs.set_progress(job["id"], status, round(progress, 4))


async def _run(job, jobs, history, clock, started, chunk, to_thread) -> Dict[str, Any]:
    request = BacktestCreate(**job["request"])
    rule = request.rule
    params = rule.params.model_dump()
    symbol, timeframe = rule.symbol.upper(), rule.timeframe

    candles = await history.load(symbol, timeframe)
    needed = required_bars(int(params["lookback"]))
    if len(candles) < needed:
        raise JobFailed(
            f"{symbol} {timeframe} has {len(candles)} bars of history; this rule needs {needed}"
        )

    start, end = first_index(params), len(candles)
    split = start + int((end - start) * request.split)
    key = tape_key(symbol, timeframe, params, candles[-1]["time"])

    tape = await jobs.get_tape(key)
    cached = tape is not None
    replay_started = clock()
    if tape is None:
        tape = []
        for lo in range(start, end, chunk):
            hi = min(end, lo + chunk)
            await _checkpoint(job, jobs, "replaying", (lo - start) / (end - start), clock, started)
            tape.extend(await to_thread(replay_range, candles, params, lo, hi))
        await _checkpoint(job, jobs, "replaying", 1.0, clock, started)
        await jobs.put_tape(key, end - start, tape)
    replay_seconds = clock() - replay_started

    await _checkpoint(job, jobs, "studying", 1.0, clock, started)
    fires = signals_from_tape(
        tape, candles, params,
        timeframe_ms=TIMEFRAME_MS[timeframe],
        persist_bars=rule.resolved_persist_bars(),
        cooldown_secs=rule.cooldown_secs,
        start=start, end=end,
    )
    setups = distinct_setups(fires)

    return {
        "meta": {
            "symbol": symbol,
            "timeframe": timeframe,
            "name": rule.name,
            "params": params,
            "neutral": request.neutral,
            "split": request.split,
            "bars": end - start,
            "warmup_bars": start,
            "from": int(candles[start]["time"]),
            "to": int(candles[-1]["time"]),
            "split_time": int(candles[split]["time"]),
            "tape_cached": cached,
            "replay_seconds": round(replay_seconds, 1),
        },
        "signals": {"fires": len(fires), "setups": len(setups)},
        "study": study(candles, setups, start=start, split=split, end=end, neutral=request.neutral),
    }
