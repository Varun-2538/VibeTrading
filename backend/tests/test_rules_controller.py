"""
The rules API around the manual test endpoint.

POST /{id}/test?emit=true calls RuleEngine.fire straight from an HTTP handler.
That is fine while the only action is an alert and wrong the moment one can
spend: it would be a trade trigger reachable by a request, outside the sweep and
with no rate limit. These pin that it stays reachable for alerts and refuses for
anything else.
"""
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers import rules_controller as rc
from controllers.rules_controller import require_owner

RULE_ID = str(uuid.uuid4())
OWNER = "0xabc"


class FakeSignal:
    def as_dict(self):
        return {"direction": "bullish", "price": 100.0}


def rule(action=None):
    return {
        "id": uuid.UUID(RULE_ID),
        "owner_key": OWNER,
        "name": "doji",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "agent": "sequence",
        "params": {"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}], "lookback": 300},
        "action": action if action is not None else {"kind": "alert"},
    }


class Rules:
    def __init__(self, row):
        self.row = row

    async def get_for_owner(self, rule_id, owner):
        return self.row if owner == OWNER else None


class Engine:
    def __init__(self, signal=None):
        self.signal, self.fired = signal, []

    async def evaluate_rule(self, row, candles, dry_run=False, **kw):
        return self.signal, None

    async def fire(self, row, signal):
        self.fired.append((row["id"], signal))
        return {"id": 1, "fired_at": None}


def client(monkeypatch, row=None, engine=None, owner=OWNER):
    async def candles(symbol, timeframe, lookback):
        return [{"time": i, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(3)]

    engine = engine or Engine(FakeSignal())
    monkeypatch.setattr(rc, "RuleRepository", Rules(rule() if row is None else row))
    monkeypatch.setattr(rc, "RuleEngine", engine)
    monkeypatch.setattr(rc.CandleService, "get_candles", staticmethod(candles))
    app = FastAPI()
    app.include_router(rc.router)
    if owner:
        app.dependency_overrides[require_owner] = lambda: owner
    return TestClient(app), engine


def test_signed_out_is_401(monkeypatch):
    api, _ = client(monkeypatch, owner=None)
    assert api.post(f"/api/rules/{RULE_ID}/test").status_code == 401


def test_another_owners_rule_is_404(monkeypatch):
    api, _ = client(monkeypatch, owner="0xsomeone-else")
    assert api.post(f"/api/rules/{RULE_ID}/test").status_code == 404


def test_an_alert_rule_can_still_be_emitted_by_hand(monkeypatch):
    api, engine = client(monkeypatch)
    res = api.post(f"/api/rules/{RULE_ID}/test?emit=true")
    assert res.status_code == 200 and res.json()["would_fire"] is True
    assert len(engine.fired) == 1


def test_an_action_that_can_spend_refuses_to_be_emitted(monkeypatch):
    api, engine = client(monkeypatch, row=rule({"kind": "dex_trade", "venue": "uniswap"}))
    res = api.post(f"/api/rules/{RULE_ID}/test?emit=true")
    assert res.status_code == 409
    assert "shadow" in res.json()["detail"]
    assert engine.fired == []  # the point: nothing was placed


def test_such_a_rule_can_still_be_tested_without_emitting(monkeypatch):
    api, engine = client(monkeypatch, row=rule({"kind": "dex_trade", "venue": "uniswap"}))
    res = api.post(f"/api/rules/{RULE_ID}/test")
    assert res.status_code == 200 and res.json()["would_fire"] is True
    assert engine.fired == []


def test_an_empty_action_is_read_as_an_alert(monkeypatch):
    """The column defaults to {"kind": "alert"}, but a null must not open the gate."""
    api, engine = client(monkeypatch, row=rule({}))
    assert api.post(f"/api/rules/{RULE_ID}/test?emit=true").status_code == 200
    assert len(engine.fired) == 1
