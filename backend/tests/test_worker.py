"""The worker: schedule shape, heartbeat, and a readable summary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import worker
from services.history_service import BackfillResult


async def test_scheduler_runs_topup_hourly_now_and_never_overlapping():
    async def topup():
        pass

    def heartbeat():
        pass

    scheduler = worker.build_scheduler(topup, heartbeat)
    job = scheduler.get_job(worker.TOPUP_JOB_ID)
    assert job.trigger.interval.total_seconds() == 3600
    assert job.max_instances == 1 and job.coalesce is True
    assert job.next_run_time is not None
    beat = scheduler.get_job("heartbeat")
    assert beat.trigger.interval.total_seconds() == 60


def test_beat_touches_the_heartbeat_file(tmp_path):
    path = tmp_path / "hb"
    worker.beat(path)
    first = path.stat().st_mtime
    worker.beat(path)
    assert path.exists() and path.stat().st_mtime >= first


def test_summary_counts_bars_and_names_failures():
    line = worker.summarise([
        BackfillResult("BTCUSDT", "1h", pages=2, bars=1500),
        BackfillResult("ETHUSDT", "5m", pages=0, bars=0, error="rate limited (429)"),
    ])
    assert "1500 bars" in line and "2 series" in line
    assert "ETHUSDT 5m: rate limited (429)" in line
