"""
The execution API: ownership, the arming gate, and the switches.

Repositories are faked, as in test_backtest_controller.py - there is no database
in the test run. What is pinned here is the contract: signed out is 401, another
wallet's rule is 404, a refusal lists every reason, and nothing can be armed
except through the gate.
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers import execution_controller as ec
from controllers.rules_controller import require_owner
from models.backtest_schemas import ExitPlan
from services.trade_plan import PARITY_VERSION

OWNER = "0xabc"
RULE_ID = str(uuid.uuid4())
JOB_ID = str(uuid.uuid4())
PARAMS = {"agent": "sequence", "steps": [{"type": "candle", "shape": "hammer"}],
          "within_bars": 3, "lookback": 300}
EXIT = {"stop_atr": 1.5, "target_r": 2.0, "max_bars": 20}
ARM = {"action": {"kind": "dex_trade", "market": "WBTC/USDC", "exit": EXIT},
       "backtest_job_id": JOB_ID}


class Rules:
    async def get_for_owner(self, rule_id, owner):
        if owner != OWNER or rule_id != RULE_ID:
            return None
        return {"id": RULE_ID, "owner_key": OWNER, "symbol": "BTCUSDT", "timeframe": "1d",
                "params": dict(PARAMS)}


class Jobs:
    def __init__(self, good=True):
        self.good = good

    async def get_for_owner(self, job_id, owner):
        if owner != OWNER or job_id != JOB_ID:
            return None
        now = datetime.now(timezone.utc)
        unseen = {"trades": 42, "expectancy_r": 0.25, "max_drawdown_pct": -12.0,
                  "cost_r": 0.05, "gross_expectancy_r": 0.30, "flags": []}
        if not self.good:
            unseen = {**unseen, "trades": 5, "expectancy_r": -0.1}
        return {
            "id": JOB_ID, "rule_id": RULE_ID, "status": "done",
            "report": {
                "meta": {"symbol": "BTCUSDT", "timeframe": "1d", "params": dict(PARAMS),
                         "neutral": "skip", "sides": "long", "exit": ExitPlan(**EXIT).model_dump(),
                         "parity_version": PARITY_VERSION,
                         "to": int((now - timedelta(hours=6)).timestamp() * 1000)},
                "trades": {"seen": {}, "unseen": unseen},
                "study": {"unseen": {"flags": []}},
                "flags": [],
            },
        }


class Accounts:
    def __init__(self, row=None):
        self.row, self.saved, self.kills = row, None, []

    async def get(self, owner):
        return self.row

    async def upsert(self, owner, settings):
        self.saved = (owner, settings)
        self.row = {"owner_key": owner, "kill_switch": False, "halted_reason": None,
                    "halted_at": None, "created_at": None, "updated_at": None, **settings}
        return self.row

    async def set_kill_switch(self, owner, on):
        self.kills.append((owner, on))
        if self.row is None:
            return None
        self.row = {**self.row, "kill_switch": on}
        return self.row


class Policies:
    def __init__(self):
        self.armed, self.disarmed = None, []

    async def arm(self, rule_id, owner, **kw):
        self.armed = (rule_id, owner, kw)
        return {"rule_id": rule_id, "owner_key": owner, "armed": True, "venue": kw["venue"],
                "market": kw["market"], "exit_plan": kw["exit_plan"], "policy": kw["policy"],
                "parity_version": kw["parity_version"], "backtest_job_id": kw["backtest_job_id"],
                "preflight": kw["preflight"], "armed_at": datetime.now(timezone.utc),
                "disarmed_reason": None}

    async def disarm(self, rule_id, reason, owner=None):
        self.disarmed.append((rule_id, reason, owner))
        return True

    async def get(self, rule_id, owner):
        return None

    async def list_for_owner(self, owner):
        return []


class Settings:
    def __init__(self, enabled=False):
        self.enabled = enabled

    async def get(self):
        return {"enabled": self.enabled, "halted_reason": None, "updated_at": None}


def client(monkeypatch, *, owner=OWNER, jobs=None, accounts=None, policies=None, settings=None):
    monkeypatch.setattr(ec, "RuleRepository", Rules())
    monkeypatch.setattr(ec, "BacktestRepository", jobs or Jobs())
    monkeypatch.setattr(ec, "ExecutionAccountRepository", accounts or Accounts())
    monkeypatch.setattr(ec, "ExecutionPolicyRepository", policies or Policies())
    monkeypatch.setattr(ec, "ExecutionSettingsRepository", settings or Settings())
    app = FastAPI()
    app.include_router(ec.router)
    if owner:
        app.dependency_overrides[require_owner] = lambda: owner
    return TestClient(app)


def test_signed_out_is_401(monkeypatch):
    api = client(monkeypatch, owner=None)
    assert api.get("/api/execution/account").status_code == 401
    assert api.post(f"/api/execution/rules/{RULE_ID}/arm", json=ARM).status_code == 401


def test_an_unconfigured_account_reads_as_off_with_the_starting_caps(monkeypatch):
    """Not an error: "off, and these are the caps you would start from"."""
    body = client(monkeypatch).get("/api/execution/account").json()
    assert body["configured"] is False and body["mode"] == "off"
    assert body["max_concurrent_positions"] == 1 and body["max_notional_usd"] == 100
    # The global brake is reported alongside, because an account that looks armed
    # while execution is off is the most confusing state to debug.
    assert body["execution_enabled"] is False
    assert body["parity_version"] == PARITY_VERSION


def test_saving_rails_stores_every_cap(monkeypatch):
    accounts = Accounts()
    res = client(monkeypatch, accounts=accounts).put(
        "/api/execution/account",
        json={"mode": "shadow", "equity_usd": 500, "max_notional_usd": 50,
              "max_concurrent_positions": 2, "max_trades_per_day": 3, "daily_loss_limit_usd": 10},
    )
    assert res.status_code == 200 and res.json()["mode"] == "shadow"
    owner, saved = accounts.saved
    assert owner == OWNER and saved["max_notional_usd"] == 50 and saved["daily_loss_limit_usd"] == 10


def test_live_mode_without_a_size_is_refused(monkeypatch):
    res = client(monkeypatch).put("/api/execution/account", json={"mode": "live", "equity_usd": 0})
    assert res.status_code == 422


def test_the_kill_switch_can_be_flipped_before_an_account_exists(monkeypatch):
    accounts = Accounts()
    res = client(monkeypatch, accounts=accounts).post("/api/execution/kill")
    assert res.status_code == 200 and res.json()["kill_switch"] is True
    assert accounts.kills[-1] == (OWNER, True)


def test_arming_a_rule_that_passed_records_the_evidence(monkeypatch):
    policies = Policies()
    res = client(monkeypatch, policies=policies).post(f"/api/execution/rules/{RULE_ID}/arm", json=ARM)
    assert res.status_code == 200
    body = res.json()
    assert body["armed"] is True and body["market"] == "WBTC/USDC"
    assert body["parity_version"] == PARITY_VERSION and body["parity_current"] is True
    assert body["backtest_job_id"] == JOB_ID
    assert body["preflight"]["passed"] is True

    rule_id, owner, kw = policies.armed
    assert (rule_id, owner) == (RULE_ID, OWNER)
    # The exit plan is stored apart from the rest of the config, verbatim, because
    # it is the one object the backtester also validates.
    assert kw["exit_plan"]["stop_atr"] == 1.5 and "exit" not in kw["policy"]
    assert kw["policy"]["sides"] == "long"


def test_a_rule_that_failed_is_409_with_every_reason(monkeypatch):
    res = client(monkeypatch, jobs=Jobs(good=False)).post(
        f"/api/execution/rules/{RULE_ID}/arm", json=ARM
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "cannot be armed" in detail["message"] and len(detail["reasons"]) >= 2


def test_preflight_reports_without_arming(monkeypatch):
    policies = Policies()
    res = client(monkeypatch, policies=policies).post(
        f"/api/execution/rules/{RULE_ID}/preflight", json=ARM
    )
    assert res.status_code == 200 and res.json()["passed"] is True
    assert policies.armed is None  # the point


def test_another_wallets_rule_is_404(monkeypatch):
    other = str(uuid.uuid4())
    api = client(monkeypatch)
    assert api.post(f"/api/execution/rules/{other}/arm", json=ARM).status_code == 404
    assert api.delete(f"/api/execution/rules/{other}/arm").status_code == 404


def test_a_backtest_belonging_to_someone_else_is_not_evidence(monkeypatch):
    res = client(monkeypatch).post(
        f"/api/execution/rules/{RULE_ID}/arm",
        json={**ARM, "backtest_job_id": str(uuid.uuid4())},
    )
    assert res.status_code == 409
    assert "belongs to this wallet" in " ".join(res.json()["detail"]["reasons"])


def test_disarming_is_always_allowed(monkeypatch):
    policies = Policies()
    res = client(monkeypatch, policies=policies).delete(f"/api/execution/rules/{RULE_ID}/arm")
    assert res.status_code == 200 and res.json()["armed"] is False
    assert policies.disarmed[-1] == (RULE_ID, "disarmed by owner", OWNER)


def test_an_action_the_schema_does_not_know_is_422(monkeypatch):
    api = client(monkeypatch)
    assert api.post(f"/api/execution/rules/{RULE_ID}/arm",
                    json={"action": {"kind": "alert"}, "backtest_job_id": JOB_ID}).status_code == 422
    assert api.post(f"/api/execution/rules/{RULE_ID}/arm",
                    json={"action": {"kind": "dex_trade", "market": "DOGE/USDC", "exit": EXIT},
                          "backtest_job_id": JOB_ID}).status_code == 422
