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
from typing import Any, Dict, List, Optional

from backtest.metrics import trade_period
from backtest.replay import first_index, replay_range, tape_key
from backtest.signals import distinct_setups, signals_from_tape
from backtest.study import study
from backtest.tuning import plan_for, tune
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


# A tuned result is the best of many tries; an untuned one is a single
# measurement. Either way the unseen period is the honest half, and a large
# drop from seen to unseen is the signature of a setting fitted to noise.
OVERFIT_RATIO = 0.5


def report_flags(trades: Dict[str, Any], *, tuned: bool) -> List[str]:
    flags = ["tuned"] if tuned else []
    seen = trades["seen"].get("expectancy_r")
    unseen = trades["unseen"].get("expectancy_r")
    if seen is not None and unseen is not None and seen > 0 and unseen < seen * OVERFIT_RATIO:
        flags.append("likely_overfit")
    return flags


def _setting(chosen: Dict[str, Any]):
    from backtest.tuning import Setting

    return Setting(chosen["filters"], chosen["stop_atr"], chosen["target_r"], chosen["max_bars"])


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
    tuning: Optional[Dict[str, Any]] = None
    active_params, active_plan = params, request.exit

    if request.tune:
        await _checkpoint(job, jobs, "tuning", 0.0, clock, started)
        def run_tuning() -> Dict[str, Any]:
            return tune(
                candles[: split + 1], tape, params, request.exit,
                neutral=request.neutral,
                start=start,
                split=split,
                grid=request.grid,
                timeframe_ms=TIMEFRAME_MS[timeframe],
                persist_bars=rule.resolved_persist_bars(),
                cooldown_secs=rule.cooldown_secs,
            )

        tuning = await to_thread(run_tuning)
        active_params = {**params, **tuning["chosen"]["filters"]}
        active_plan = plan_for(request.exit, _setting(tuning["chosen"]))
        await _checkpoint(job, jobs, "studying", 1.0, clock, started)

    fires = signals_from_tape(
        tape, candles, active_params,
        timeframe_ms=TIMEFRAME_MS[timeframe],
        persist_bars=rule.resolved_persist_bars(),
        cooldown_secs=rule.cooldown_secs,
        start=start, end=end,
    )
    setups = distinct_setups(fires)
    trades = {
        "seen": trade_period(candles, setups, start, split, active_plan, request.neutral, TIMEFRAME_MS[timeframe]),
        "unseen": trade_period(candles, setups, split, end, active_plan, request.neutral, TIMEFRAME_MS[timeframe]),
    }

    report: Dict[str, Any] = {
        "meta": {
            "symbol": symbol,
            "timeframe": timeframe,
            "name": rule.name,
            "params": active_params,
            "neutral": request.neutral,
            "split": request.split,
            "bars": end - start,
            "warmup_bars": start,
            "from": int(candles[start]["time"]),
            "to": int(candles[-1]["time"]),
            "split_time": int(candles[split]["time"]),
            "tape_cached": cached,
            "replay_seconds": round(replay_seconds, 1),
            "exit": active_plan.model_dump(),
        },
        "signals": {"fires": len(fires), "setups": len(setups)},
        "study": study(candles, setups, start=start, split=split, end=end, neutral=request.neutral),
        "trades": trades,
        "flags": report_flags(trades, tuned=request.tune),
    }
    if tuning is not None:
        report["tuning"] = tuning
    return report
