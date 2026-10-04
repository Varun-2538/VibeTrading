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


def test_the_account_publishes_where_vaults_can_live(monkeypatch):
    """
    The factory a browser deploys through has to be the one the executor reads, so
    it is published here. A chain without one is listed as null, not hidden.
    """
    monkeypatch.setattr(ec.settings, "arbitrum_vault_factory_address", "")
    monkeypatch.setattr(ec.settings, "robinhood_vault_factory_address", "0x" + "b" * 40)
    chains = {c["key"]: c for c in client(monkeypatch).get("/api/execution/account").json()["chains"]}

    assert chains["robinhood"]["chain_id"] == 4663
    assert chains["robinhood"]["stable_symbol"] == "USDG"
    assert chains["robinhood"]["factory"] == "0x" + "b" * 40
    assert {"WETH/USDG", "NVDA/USDG", "TSLA/USDG"} <= set(chains["robinhood"]["markets"])
    assert "NVDA/USDG" in chains["robinhood"]["stock_markets"]
    assert chains["arbitrum"]["stock_markets"] == []
    assert chains["arbitrum"]["factory"] is None
    assert set(chains["arbitrum"]["markets"]) == {"WETH/USDC", "WBTC/USDC"}


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


class Positions:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def list_for_owner(self, owner, limit=50):
        return [r for r in self.rows if r["owner_key"] == owner]

    async def get(self, position_id, owner=None):
        for r in self.rows:
            if str(r["id"]) == str(position_id) and (owner is None or r["owner_key"] == owner):
                return r
        return None


class Queue:
    def __init__(self):
        self.rows = []

    async def list_for_owner(self, owner, status=None, limit=50):
        return [r for r in self.rows if r["owner_key"] == owner and (status is None or r["status"] == status)]

    async def stuck(self, older_than_seconds=300):
        return []


class Orders:
    async def for_intent(self, intent_id):
        return [{"id": 1, "client_order_id": "abc", "leg": "entry", "status": "filled",
                 "venue_order_id": None, "submitted_at": None, "acked_at": None,
                 "request": {"notional_usd": 100.0}, "response": {}, "error": None}]

    async def in_doubt(self):
        return []


class Fills:
    async def for_position(self, position_id):
        return [{"price": 2000.0, "qty": 0.05, "fee_usd": 0.05, "gas_usd": 0.3,
                 "tx_ref": "0xabc", "filled_at": None, "venue_fill_id": "f1"}]


class Audit:
    async def for_position(self, position_id):
        return [{"at": None, "actor": "executor", "from_status": None, "to_status": "open",
                 "reason": "opened", "detail": {"price": 2000.0}}]


POSITION_ROW = {
    "id": uuid.uuid4(), "owner_key": OWNER, "rule_id": uuid.UUID(RULE_ID), "status": "open",
    "mode": "shadow", "venue": "uniswap_v3_arbitrum", "market": "WBTC/USDC", "symbol": "BTCUSDT",
    "timeframe": "1d", "direction": 1, "entry_price": 2000.0, "qty": 0.05, "notional_usd": 100.0,
    "stop_price": 1900.0, "target_price": 2200.0, "deadline_bar_time": None, "opened_at": None,
    "closed_at": None, "exit_price": None, "exit_reason": None, "realised_pnl_usd": None,
    "realised_r": None, "reference": {"entry_drift_bps": 3.5}, "plan": {"stop_atr": 1.5},
    "parity_version": PARITY_VERSION, "entry_intent_id": uuid.uuid4(),
}


def with_positions(monkeypatch, rows=None, queue=None):
    monkeypatch.setattr(ec, "ExecutionPositionRepository", Positions(rows if rows is not None else [POSITION_ROW]))
    monkeypatch.setattr(ec, "ExecutionIntentRepository", queue or Queue())
    monkeypatch.setattr(ec, "ExecutionOrderRepository", Orders())
    monkeypatch.setattr(ec, "ExecutionFillRepository", Fills())
    monkeypatch.setattr(ec, "ExecutionAuditRepository", Audit())
    return client(monkeypatch)


def test_positions_are_listed_for_their_owner(monkeypatch):
    api = with_positions(monkeypatch)
    body = api.get("/api/execution/positions").json()
    assert len(body) == 1 and body[0]["direction"] == "long"
    assert body[0]["stop_price"] == 1900.0 and body[0]["mode"] == "shadow"


def test_the_audit_view_carries_the_whole_chain(monkeypatch):
    """What someone disputing a fill needs: why, what was decided, what was sent."""
    api = with_positions(monkeypatch)
    body = api.get(f"/api/execution/positions/{POSITION_ROW['id']}").json()
    assert body["position"]["id"] == str(POSITION_ROW["id"])
    assert body["plan"]["stop_atr"] == 1.5 and body["parity_current"] is True
    assert body["orders"][0]["request"]["notional_usd"] == 100.0
    assert body["fills"][0]["gas_usd"] == 0.3
    assert body["audit"][0]["actor"] == "executor"
    # The parity number, which is what a dispute about slippage is answered with.
    assert body["position"]["reference"]["entry_drift_bps"] == 3.5


def test_another_wallets_position_is_404(monkeypatch):
    api = with_positions(monkeypatch, rows=[{**POSITION_ROW, "owner_key": "0xsomeone-else"}])
    assert api.get(f"/api/execution/positions/{POSITION_ROW['id']}").status_code == 404


def test_health_says_whether_anything_is_actually_running(monkeypatch):
    api = with_positions(monkeypatch)
    body = api.get("/api/execution/health").json()
    # Armed is not the same as running, and this is the endpoint that can tell them
    # apart: execution ships globally off.
    assert body["execution_enabled"] is False
    assert body["mode"] == "off" and body["open_positions"] == 1
    assert body["stuck_intents"] == 0 and body["orders_in_doubt"] == 0
