"""Fills that err against the strategy, and the account they add up to."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.signals import TapeSignal
from backtest.trades import simulate
from models.backtest_schemas import ExitPlan
from walks import H, T0

FREE = dict(fee_pct=0, slippage_pct=0)
FLAT = (100, 100.5, 99.5, 100)


def bars(*ohlc):
    return [{"time": T0 + i * H, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
            for i, (o, h, l, c) in enumerate(ohlc)]


def sig(i, direction="bullish"):
    return TapeSignal(i, T0 + i * H, f"s{i}", direction, False)


def plan(**kw):
    base = dict(stop_pct=2, target_pct=4, max_bars=50, **FREE)
    base.update(kw)
    return ExitPlan(**base)


def one(candles, signals, p, hi=None, neutral="skip"):
    return simulate(candles, signals, 0, hi or len(candles), p, neutral)


def test_a_bar_touching_stop_and_target_is_a_stop():
    t = one(bars(FLAT, (100, 105, 97, 101), FLAT), [sig(0)], plan()).trades[0]
    assert (t.entry_index, t.exit_index, t.reason, t.exit) == (1, 1, "stop", 98.0)
    assert t.r == pytest.approx(-1.0)


def test_gap_through_the_stop_fills_at_the_open():
    t = one(bars(FLAT, (100, 101, 99, 100), (95, 96, 94, 95), FLAT), [sig(0)], plan()).trades[0]
    assert (t.exit_index, t.reason, t.exit) == (2, "stop", 95.0)
    assert t.r == pytest.approx(-2.5)


def test_gap_through_the_target_fills_at_the_better_open():
    t = one(bars(FLAT, (100, 101, 99, 100), (106, 107, 105, 106), FLAT), [sig(0)], plan()).trades[0]
    assert (t.reason, t.exit) == ("target", 106.0) and t.r == pytest.approx(3.0)


def test_bar_limit_exits_at_the_next_open():
    t = one(bars(FLAT, FLAT, FLAT, (101, 101.5, 100.5, 101), FLAT), [sig(0)], plan(max_bars=2)).trades[0]
    assert (t.exit_index, t.reason, t.exit) == (3, "time", 101.0)


def test_an_opposite_signal_exits_at_the_next_open_and_is_not_traded():
    sim = one(bars(FLAT, FLAT, FLAT, FLAT, FLAT), [sig(0), sig(1, "bearish")], plan(exit_on_opposite=True))
    assert [(t.exit_index, t.reason) for t in sim.trades] == [(2, "opposite")]
    assert sim.skipped_in_position == 1


def test_a_trade_open_at_the_split_closes_at_the_boundary_open():
    candles = bars(FLAT, FLAT, FLAT, (102, 102.5, 101.5, 102), FLAT)
    t = one(candles, [sig(0)], plan(), hi=3).trades[0]
    assert (t.exit_index, t.reason, t.exit) == (3, "end", 102.0)


def test_short_trades_mirror_long_ones():
    t = one(bars(FLAT, (100, 103, 99, 101), FLAT), [sig(0, "bearish")], plan()).trades[0]
    assert (t.direction, t.stop, t.reason, t.exit) == (-1, 102.0, "stop", 102.0)


def test_costs_are_paid_on_both_sides():
    t = one(bars(FLAT, (100, 105, 99, 104), FLAT), [sig(0)], plan(fee_pct=0.1, slippage_pct=0.1)).trades[0]
    entry = 100 * 1.001
    fill = entry * 1.04 * 0.999
    assert t.entry == pytest.approx(entry) and t.exit == pytest.approx(fill)
    assert t.ret == pytest.approx((fill - entry) / entry - 0.001 * (1 + fill / entry))


def test_risk_sizes_the_position_and_never_levers():
    wide = one(bars(FLAT, (100, 105, 99, 104), FLAT), [sig(0)], plan(stop_pct=2)).trades[0]
    tight = one(bars(FLAT, (100, 105, 99, 104), FLAT), [sig(0)], plan(stop_pct=0.5)).trades[0]
    assert wide.notional == pytest.approx(0.5) and tight.notional == pytest.approx(1.0)


def test_atr_stop_uses_the_range_at_the_signal_bar():
    flat = [(100, 101, 99, 100)] * 20
    t = one(bars(*flat), [sig(16)], ExitPlan(stop_atr=1.5, target_r=None, max_bars=2, **FREE)).trades[0]
    assert t.stop == pytest.approx(97.0) and t.target is None


def test_neutral_signals_follow_the_choice_and_late_signals_have_no_room():
    candles = bars(FLAT, (100, 105, 99, 104), FLAT)
    assert one(candles, [sig(0, "neutral")], plan()).skipped_neutral == 1
    assert len(one(candles, [sig(0, "neutral")], plan(), neutral="long").trades) == 1
    assert one(candles, [sig(2)], plan()).skipped_no_room == 1


def test_one_position_at_a_time():
    sim = one(bars(*[FLAT] * 6), [sig(0), sig(1), sig(3)], plan(max_bars=2))
    assert [t.entry_index for t in sim.trades] == [1, 4] and sim.skipped_in_position == 1


from backtest.metrics import max_drawdown_pct, trade_period


def test_metrics_add_up_by_hand():
    candles = bars(FLAT, (100, 105, 99, 104), FLAT, (100, 101, 97, 98), FLAT, FLAT, FLAT, FLAT)
    m = trade_period(candles, [sig(0), sig(2)], 0, 8, plan(), "skip", H)
    assert m["trades"] == 2 and m["win_rate"] == 0.5
    assert (m["expectancy_r"], m["avg_win_r"], m["avg_loss_r"]) == (0.5, 2.0, -1.0)
    assert m["profit_factor"] == 2.0
    assert m["total_return_pct"] == pytest.approx(0.98, abs=1e-3)
    assert m["max_drawdown_pct"] == pytest.approx(-1.0, abs=1e-3)
    assert m["exposure_pct"] == 25.0 and m["longest_losing_streak"] == 1 and m["buy_hold_pct"] == 0.0
    assert [t["reason"] for t in m["trade_list"]] == ["target", "stop"]
    assert m["trade_list"][0]["direction"] == "long" and m["trade_list"][0]["entry_time"] == T0 + H
    assert m["equity"][0] == [T0, 1.0] and m["equity"][-1][1] == pytest.approx(1.0098, abs=1e-5)
    assert m["flags"] == ["too_few_trades"]


def test_drawdown_and_an_account_that_never_traded():
    assert max_drawdown_pct([1.0, 1.2, 0.9, 1.3]) == pytest.approx(-25.0)
    m = trade_period(bars(*[FLAT] * 10), [], 0, 10, plan(), "skip", H)
    assert m["trades"] == 0 and m["sharpe"] is None and m["expectancy_r"] is None
    assert m["profit_factor"] is None and m["equity"][-1][1] == 1.0
