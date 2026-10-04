"""
What a rule's execution config may be.

The discriminated union is the whole point: a misspelled field has to be refused
when it is written, because the alternative is a config that is accepted and then
spends money on terms nobody validated.
"""
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.backtest_schemas import ExitPlan
from models.execution_schemas import (
    AccountSettings,
    ArmRequest,
    DexTradeActionConfig,
    PreflightThresholds,
    RuleAction,
)

ACTIONS = TypeAdapter(RuleAction)
EXIT = {"stop_atr": 1.5, "target_r": 2.0, "max_bars": 20}


def action(**kw):
    kw.setdefault("exit", ExitPlan(**EXIT))
    return DexTradeActionConfig(market="WETH/USDC", **kw)


def test_the_union_reads_the_kind_and_refuses_an_unknown_one():
    assert ACTIONS.validate_python({"kind": "alert"}).kind == "alert"
    assert ACTIONS.validate_python({"kind": "dex_trade", "market": "WETH/USDC", "exit": EXIT}).market == "WETH/USDC"
    with pytest.raises(ValidationError):
        ACTIONS.validate_python({"kind": "carrier_pigeon"})


def test_a_trade_action_needs_a_market_and_a_plan():
    with pytest.raises(ValidationError):
        ACTIONS.validate_python({"kind": "dex_trade", "exit": EXIT})
    with pytest.raises(ValidationError):
        ACTIONS.validate_python({"kind": "dex_trade", "market": "DOGE/USDC", "exit": EXIT})
    with pytest.raises(ValidationError):
        ACTIONS.validate_python({"kind": "dex_trade", "market": "WETH/USDC"})


def test_the_nested_exit_plan_keeps_its_own_rules():
    """One type for how a signal becomes a trade, so its validator still fires."""
    with pytest.raises(ValidationError) as exc:
        DexTradeActionConfig(market="WETH/USDC", exit={"stop_atr": None, "stop_pct": None})
    assert "needs a stop" in str(exc.value)


def test_a_live_trade_needs_a_way_out_that_is_not_the_stop():
    with pytest.raises(ValidationError) as exc:
        action(exit=ExitPlan(stop_atr=1.5, target_r=None, target_pct=None, max_bars=400))
    assert "way out" in str(exc.value)
    # A target is a way out; so is a bar limit that will actually arrive.
    assert action(exit=ExitPlan(stop_atr=1.5, target_r=None, max_bars=40)).exit.max_bars == 40


def test_a_pool_cannot_short_so_sides_is_not_a_choice():
    assert action().sides == "long"
    with pytest.raises(ValidationError):
        ACTIONS.validate_python({"kind": "dex_trade", "market": "WETH/USDC", "exit": EXIT, "sides": "both"})


def test_defaults_are_the_cautious_end_of_every_range():
    a = action()
    assert (a.max_entry_delay_secs, a.max_slippage_bps, a.max_notional_usd) == (120, 50, 100)
    assert a.neutral == "skip"


class TestThresholds:
    def test_the_owner_sets_the_bar_but_not_the_floor(self):
        """
        Their money, their patience - but there is no reading of a losing unseen
        result that makes it evidence, so zero is not available.
        """
        assert PreflightThresholds().min_expectancy_r == 0.10
        assert PreflightThresholds(min_expectancy_r=0.5).min_expectancy_r == 0.5
        with pytest.raises(ValidationError):
            PreflightThresholds(min_expectancy_r=0)
        with pytest.raises(ValidationError):
            PreflightThresholds(min_expectancy_r=-0.2)

    def test_the_sample_size_is_not_a_preference(self):
        assert PreflightThresholds().min_trades == 30
        with pytest.raises(ValidationError):
            PreflightThresholds(min_trades=5)


class TestArmRequest:
    def test_the_evidence_is_named_not_searched_for(self):
        body = ArmRequest(action=action(), backtest_job_id="abc")
        assert body.backtest_job_id == "abc" and body.thresholds.min_trades == 30
        with pytest.raises(ValidationError):
            ArmRequest(action=action())


class TestAccountSettings:
    def test_it_starts_off_with_the_tightest_useful_caps(self):
        s = AccountSettings()
        assert s.mode == "off" and s.max_concurrent_positions == 1
        assert (s.max_notional_usd, s.max_trades_per_day, s.daily_loss_limit_usd) == (100, 5, 25)

    def test_live_mode_needs_a_size_to_trade_with(self):
        with pytest.raises(ValidationError) as exc:
            AccountSettings(mode="live")
        assert "equity_usd" in str(exc.value)
        assert AccountSettings(mode="live", equity_usd=500).equity_usd == 500
        # Shadow needs nothing: it spends nothing.
        assert AccountSettings(mode="shadow").mode == "shadow"

    def test_caps_are_bounded_on_both_sides(self):
        with pytest.raises(ValidationError):
            AccountSettings(max_notional_usd=0)
        with pytest.raises(ValidationError):
            AccountSettings(max_concurrent_positions=50)
