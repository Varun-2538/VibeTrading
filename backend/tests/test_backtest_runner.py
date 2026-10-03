"""Orchestration: chunks, progress, the tape cache, cancel, timeout, failure."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest import runner
from walks import doji_series

REQUEST = {
    "rule": {"name": "doji", "symbol": "BTCUSDT", "timeframe": "1h", "cooldown_secs": 0,
             "params": {"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}], "lookback": 60}},
    "neutral": "long",
    "split": 0.7,
}


class FakeJobs:
    def __init__(self, cancel_after=None):
        self.progress, self.tapes, self.finished, self.failed = [], {}, None, None
        self.cancel_after = cancel_after
        self.puts = 0

    async def status_of(self, job_id):
        if self.cancel_after is not None and len(self.progress) >= self.cancel_after:
            return "cancelled"
        return "replaying"

    async def set_progress(self, job_id, status, progress):
        self.progress.append((status, progress))

    async def get_tape(self, key):
        return self.tapes.get(key)

    async def put_tape(self, key, bars, rows):
        self.puts += 1
        self.tapes[key] = rows

    async def finish(self, job_id, report):
        self.finished = report

    async def fail(self, job_id, error):
        self.failed = error


class FakeHistory:
    def __init__(self, candles):
        self.candles = candles

    async def load(self, symbol, timeframe, start_ms=0, end_ms=None):
        return self.candles


async def direct(fn, *args):
    return fn(*args)


def job():
    return {"id": "j1", "request": REQUEST}


async def test_a_job_runs_to_a_report_with_rising_progress():
    jobs = FakeJobs()
    report = await runner.run_job(job(), jobs=jobs, history=FakeHistory(doji_series(900)), chunk=200, to_thread=direct)
    assert jobs.finished == report and jobs.failed is None
    replaying = [p for s, p in jobs.progress if s == "replaying"]
    assert replaying == sorted(replaying) and replaying[-1] == 1.0
    assert jobs.progress[-1][0] == "studying"
    assert report["meta"]["tape_cached"] is False and report["meta"]["warmup_bars"] == 58
    assert report["signals"]["setups"] > 0
    assert set(report["study"]) == {"seen", "unseen"}


async def test_a_second_run_reuses_the_tape_and_reports_the_same_study():
    jobs, history = FakeJobs(), FakeHistory(doji_series(900))
    first = await runner.run_job(job(), jobs=jobs, history=history, chunk=200, to_thread=direct)
    second = await runner.run_job(job(), jobs=jobs, history=history, chunk=200, to_thread=direct)
    assert jobs.puts == 1 and second["meta"]["tape_cached"] is True
    assert second["study"] == first["study"]


async def test_cancel_stops_between_chunks_without_touching_the_job():
    jobs = FakeJobs(cancel_after=1)
    assert await runner.run_job(job(), jobs=jobs, history=FakeHistory(doji_series(900)), chunk=200, to_thread=direct) is None
    assert jobs.finished is None and jobs.failed is None and jobs.puts == 0


async def test_too_little_history_fails_with_a_reason():
    jobs = FakeJobs()
    await runner.run_job(job(), jobs=jobs, history=FakeHistory(doji_series(100)), to_thread=direct)
    assert "100 bars" in jobs.failed and "needs 359" in jobs.failed


async def test_a_job_past_its_time_limit_fails():
    ticks = iter([0.0] + [runner.JOB_TIMEOUT_SECONDS + 1.0] * 50)
    jobs = FakeJobs()
    await runner.run_job(job(), jobs=jobs, history=FakeHistory(doji_series(900)), chunk=200,
                         to_thread=direct, clock=lambda: next(ticks))
    assert jobs.failed.startswith("timeout")


async def test_the_report_carries_trades_for_both_periods():
    report = await runner.run_job(job(), jobs=FakeJobs(), history=FakeHistory(doji_series(900)), chunk=200, to_thread=direct)
    assert set(report["trades"]) == {"seen", "unseen"}
    assert report["meta"]["exit"]["max_bars"] == 20
    seen = report["trades"]["seen"]
    assert seen["trades"] > 0 and seen["equity"][0][1] == 1.0
