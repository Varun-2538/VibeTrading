"""
The gate between a backtest and a rule that can spend.

Two families of check and both matter. Identity: is this report about this rule,
armed this way? Quality: did it work on data the tuner never saw? The tests are
written as "what a passing report looks like, then one thing wrong at a time",
because that is how the failures will actually arrive.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.backtest_schemas import ExitPlan
from models.execution_schemas import DexTradeActionConfig, PreflightThresholds
from services.execution.preflight import MAX_EVIDENCE_AGE_DAYS, check
from services.trade_plan import PARITY_VERSION

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
RULE_ID = "11111111-1111-1111-1111-111111111111"
JOB_ID = "22222222-2222-2222-2222-222222222222"
PARAMS = {"agent": "sequence", "steps": [{"type": "candle", "shape": "hammer"}],
          "within_bars": 3, "lookback": 300}
EXIT = dict(stop_atr=1.5, target_r=2.0, max_bars=20)


def rule(**over):
    base = {"id": RULE_ID, "owner_key": "0xabc", "symbol": "BTCUSDT", "timeframe": "1d",
            "params": dict(PARAMS)}
    base.update(over)
    return base


def action(**over):
    over.setdefault("exit", ExitPlan(**EXIT))
    return DexTradeActionConfig(market="WBTC/USDC", **over)


def job(*, meta=None, unseen=None, study=None, flags=None, **over):
    plan = ExitPlan(**EXIT).model_dump()
    base_meta = {
        "symbol": "BTCUSDT", "timeframe": "1d", "params": dict(PARAMS), "neutral": "skip",
        "sides": "long", "exit": plan, "parity_version": PARITY_VERSION,
        "to": int((NOW - timedelta(days=1)).timestamp() * 1000),
    }
    base_meta.update(meta or {})
    base_unseen = {"trades": 42, "expectancy_r": 0.25, "max_drawdown_pct": -12.0,
                   "cost_r": 0.05, "gross_expectancy_r": 0.30, "flags": []}
    base_unseen.update(unseen or {})
    row = {
        "id": JOB_ID,
        "rule_id": RULE_ID,
        "status": "done",
        "report": {
            "meta": base_meta,
            "trades": {"seen": {}, "unseen": base_unseen},
            "study": {"unseen": study if study is not None else {"flags": []}},
            "flags": flags or [],
        },
    }
    row.update(over)
    return row


def gate(the_job=None, the_action=None, the_rule=None, **kw):
    return check(
        the_rule or rule(),
        the_action or action(),
        job() if the_job is None else the_job,
        thresholds=kw.pop("thresholds", PreflightThresholds()),
        now=kw.pop("now", NOW),
        **kw,
    )


def test_a_good_report_arms_the_rule():
    result = gate()
    assert result.passed and result.reasons == []
    assert result.evidence["unseen_trades"] == 42
    assert result.evidence["unseen_expectancy_r"] == 0.25
    assert result.evidence["sides"] == "long"
    assert result.evidence["thresholds"]["min_trades"] == 30


class TestIdentity:
    def test_no_backtest_at_all(self):
        result = check(rule(), action(), None, thresholds=PreflightThresholds(), now=NOW)
        assert not result.passed and "belongs to this wallet" in result.reasons[0]

    def test_a_backtest_that_has_not_finished(self):
        result = gate(job(status="queued"))
        assert not result.passed and "not done" in result.reasons[0]

    def test_a_report_for_a_different_rule(self):
        result = gate(job(rule_id="99999999-9999-9999-9999-999999999999"))
        assert "not run for this rule" in " ".join(result.reasons)

    def test_a_report_on_another_pair_or_timeframe(self):
        assert "ETHUSDT" in " ".join(gate(job(meta={"symbol": "ETHUSDT"})).reasons)
        assert "1h" in " ".join(gate(job(meta={"timeframe": "1h"})).reasons)

    def test_settings_that_moved_since_the_report(self):
        changed = dict(PARAMS)
        changed["within_bars"] = 5
        result = gate(job(meta={"params": changed}))
        assert "settings have changed" in " ".join(result.reasons)

    def test_an_exit_plan_that_differs_names_the_fields(self):
        result = gate(job(meta={"exit": ExitPlan(stop_atr=2.5, target_r=1.0, max_bars=20).model_dump()}))
        reasons = " ".join(result.reasons)
        assert "exit plan differs" in reasons and "stop_atr" in reasons and "target_r" in reasons

    def test_costs_are_not_part_of_that_comparison(self):
        """
        A report measured through a dearer pool is still evidence about the same
        strategy - live pays what the chain charges and measures it. Only the
        behavioural fields have to match.
        """
        dearer = ExitPlan(**EXIT, fee_pct=0.3, gas_usd=2.0).model_dump()
        assert gate(job(meta={"exit": dearer})).passed

    def test_a_report_that_measured_shorts_is_not_evidence_for_a_pool(self):
        result = gate(job(meta={"sides": "both"}))
        assert not result.passed and "cannot short" in " ".join(result.reasons)

    def test_a_different_reading_of_directionless_signals(self):
        result = gate(job(meta={"neutral": "long"}))
        assert "directionless" in " ".join(result.reasons)

    def test_older_exit_arithmetic(self):
        result = gate(job(meta={"parity_version": PARITY_VERSION - 1}))
        assert "different exit arithmetic" in " ".join(result.reasons)

    def test_stale_evidence(self):
        old = int((NOW - timedelta(days=MAX_EVIDENCE_AGE_DAYS + 3)).timestamp() * 1000)
        result = gate(job(meta={"to": old}))
        assert "evidence has to be newer" in " ".join(result.reasons)

    def test_a_bar_limit_longer_than_a_position_should_live(self):
        """max_bars 500 is a fine backtest question and a 16-month live hold."""
        result = gate(the_action=action(exit=ExitPlan(stop_atr=1.5, target_r=2.0, max_bars=500)))
        assert "longer than" in " ".join(result.reasons)


class TestQuality:
    def test_too_few_unseen_trades(self):
        result = gate(job(unseen={"trades": 12}))
        assert "12 unseen trades" in " ".join(result.reasons)

    def test_expectancy_below_the_owners_bar(self):
        result = gate(job(unseen={"expectancy_r": 0.04}))
        assert "below your" in " ".join(result.reasons)
        # And the owner can lower their own bar, within reason.
        assert gate(job(unseen={"expectancy_r": 0.04}),
                    thresholds=PreflightThresholds(min_expectancy_r=0.02)).passed

    def test_a_losing_unseen_result_can_never_be_armed(self):
        """There is no threshold at which a loss becomes evidence."""
        assert not gate(job(unseen={"expectancy_r": -0.5})).passed

    def test_drawdown_worse_than_allowed(self):
        result = gate(job(unseen={"max_drawdown_pct": -40.0}))
        assert "worse than your" in " ".join(result.reasons)
        assert gate(job(unseen={"max_drawdown_pct": -40.0}),
                    thresholds=PreflightThresholds(max_drawdown_pct=50)).passed

    def test_a_collapse_between_seen_and_unseen(self):
        result = gate(job(flags=["tuned", "likely_overfit"]))
        assert "fit noise" in " ".join(result.reasons)

    def test_tuning_alone_is_not_disqualifying(self):
        """Searching settings is allowed; keeping the ones that only fit noise is not."""
        assert gate(job(flags=["tuned"])).passed
        assert gate(job(flags=["tuned"])).evidence["tuned"] is True

    def test_the_reports_own_flags_are_honoured(self):
        assert "too few unseen trades" in " ".join(gate(job(unseen={"flags": ["too_few_trades"]})).reasons)
        assert "no edge" in " ".join(gate(job(study={"flags": ["no_edge_detected"]})).reasons)


class TestCostHonesty:
    def test_an_account_paying_more_than_the_report_assumed(self):
        result = gate(realised_cost_r=0.30, positions_closed=25)
        assert not result.passed
        assert "really pays" in " ".join(result.reasons)

    def test_it_waits_until_there_are_fills_to_compare(self):
        assert gate(realised_cost_r=0.30, positions_closed=3).passed

    def test_costs_close_to_the_model_are_fine(self):
        assert gate(realised_cost_r=0.06, positions_closed=25).passed


class TestOverride:
    def test_a_quality_failure_is_advice_the_owner_may_overrule(self):
        result = gate(job(unseen={"expectancy_r": -0.2}, study={"flags": ["no_edge_detected"]}))
        assert not result.passed and result.overridable
        assert result.as_dict()["overridable"] is True

    def test_an_identity_failure_cannot_be_overruled(self):
        """A report about another rule says nothing about this one, whatever the owner wants."""
        result = gate(job(rule_id="33333333-3333-3333-3333-333333333333", unseen={"expectancy_r": -0.2}))
        assert not result.passed and not result.overridable
        assert not gate(job(meta={"sides": "both"})).overridable

    def test_a_pass_has_nothing_to_overrule(self):
        assert not gate().overridable


def test_every_failure_is_reported_not_just_the_first():
    """
    An owner fixing one at a time learns nothing about the rest, and this is the
    only place that will ever tell them why their strategy may not spend.
    """
    result = gate(job(meta={"sides": "both", "timeframe": "1h"}, unseen={"trades": 4, "expectancy_r": -0.2}))
    assert not result.passed and len(result.reasons) >= 4
