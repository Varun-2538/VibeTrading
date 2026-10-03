"""The backtest API: ownership, one job at a time, history required."""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers import backtest_controller as bc
from controllers.rules_controller import require_owner

BODY = {"rule": {"name": "doji", "symbol": "BTCUSDT", "timeframe": "1h",
                 "params": {"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}]}}}
JOB_ID = str(uuid.uuid4())


class Jobs:
    def __init__(self, active=0):
        self.active, self.created = active, None

    async def count_active(self, owner):
        return self.active

    async def create(self, owner, request):
        self.created = (owner, request)
        return {"id": uuid.UUID(JOB_ID), "status": "queued", "created_at": datetime.now(timezone.utc)}

    async def get_for_owner(self, job_id, owner):
        if owner != "0xabc":
            return None
        return {"id": uuid.UUID(job_id), "owner_key": owner, "status": "done", "progress": 1.0,
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "started_at": None,
                "finished_at": None, "request": BODY, "report": {"study": {}}, "error": None}

    async def cancel_or_delete(self, job_id, owner):
        return "cancelled" if owner == "0xabc" else None


def client(monkeypatch, jobs, bars=100_000, owner="0xabc"):
    async def coverage():
        return {"depth_days": {}, "series": [{"symbol": "BTCUSDT", "timeframe": "1h", "bars": bars}]}

    monkeypatch.setattr(bc, "BacktestRepository", jobs)
    monkeypatch.setattr(bc, "get_coverage", coverage)
    app = FastAPI()
    app.include_router(bc.router)
    if owner:
        app.dependency_overrides[require_owner] = lambda: owner
    return TestClient(app)


def test_signed_out_is_401(monkeypatch):
    assert client(monkeypatch, Jobs(), owner=None).post("/api/backtests", json=BODY).status_code == 401


def test_create_queues_a_job_for_the_owner(monkeypatch):
    jobs = Jobs()
    res = client(monkeypatch, jobs).post("/api/backtests", json=BODY)
    assert res.status_code == 201 and res.json() == {"id": JOB_ID, "status": "queued"}
    owner, request = jobs.created
    assert owner == "0xabc" and request["rule"]["params"]["lookback"] == 300 and request["split"] == 0.7


def test_a_second_active_job_is_429(monkeypatch):
    assert client(monkeypatch, Jobs(active=1)).post("/api/backtests", json=BODY).status_code == 429


def test_missing_history_is_409_with_the_numbers(monkeypatch):
    res = client(monkeypatch, Jobs(), bars=400).post("/api/backtests", json=BODY)
    assert res.status_code == 409 and "400" in res.json()["detail"] and "599" in res.json()["detail"]


def test_unsupported_timeframe_is_422(monkeypatch):
    body = {"rule": {**BODY["rule"], "timeframe": "1m"}}
    assert client(monkeypatch, Jobs()).post("/api/backtests", json=body).status_code == 422


def test_get_is_scoped_to_the_owner(monkeypatch):
    assert client(monkeypatch, Jobs()).get(f"/api/backtests/{JOB_ID}").json()["status"] == "done"
    assert client(monkeypatch, Jobs(), owner="0xother").get(f"/api/backtests/{JOB_ID}").status_code == 404


def test_delete_reports_what_happened(monkeypatch):
    assert client(monkeypatch, Jobs()).delete(f"/api/backtests/{JOB_ID}").json() == {"result": "cancelled"}
    assert client(monkeypatch, Jobs(), owner="0xother").delete(f"/api/backtests/{JOB_ID}").status_code == 404
