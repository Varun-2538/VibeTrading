"""
The shared trade maths, and the proof a live executor can use it.

backtest/trades.py now delegates to these functions, so test_backtest_trades.py
passing unchanged is what says the extraction changed nothing. What is tested
here is the thing that file cannot see: that consuming one bar at a time - the
way a monitor will, holding a deadline rather than a loop counter - reaches the
same exit as replaying the whole array at once.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.signals import TapeSignal
from backtest.trades import simulate
from models.backtest_schemas import ExitPlan
from services.trade_plan import (
    BEHAVIOURAL_FIELDS,
    COST_FIELDS,
    PARITY_VERSION,
    bar_exit,
    bracket,
    entry_price,
    frictionless_return,
    in_r,
    notional_fraction,
    notional_usd,
    signed_direction,
    stop_distance,
    tradable,
    time_exit_bar_index,
    trade_return,
)
from walks import H, T0, random_walk

FREE = dict(fee_pct=0, slippage_pct=0)


def bars(*ohlc):
    return [{"time": T0 + i * H, "open": o, "high": h, "low": lo, "close": c, "volume": 1.0}
            for i, (o, h, lo, c) in enumerate(ohlc)]


class TestBarExit:
    def test_a_bar_touching_stop_and_target_is_a_stop(self):
        assert bar_exit(100, 105, 97, 1, 98, 104, first_bar=True) == (98, "stop")

    def test_a_gap_through_the_stop_fills_at_that_open(self):
        assert bar_exit(95, 96, 94, 1, 98, 104, first_bar=False) == (95, "stop")

    def test_a_gap_through_the_target_fills_at_the_better_open(self):
        """Honesty runs both ways: the gap is not only ever against you."""
        assert bar_exit(106, 107, 105, 1, 98, 104, first_bar=False) == (106, "target")

    def test_the_entry_bar_has_no_gap_check(self):
        """
        The position was opened at this open, so the same open cannot also be a
        gap through the level. Without the flag every trade whose stop sits above
        its entry open would exit instantly at entry.
        """
        assert bar_exit(95, 96, 94, 1, 98, 104, first_bar=True) == (98, "stop")

    def test_a_quiet_bar_does_nothing(self):
        assert bar_exit(100, 101, 99, 1, 98, 104, first_bar=False) is None

    def test_a_short_mirrors_a_long(self):
        assert bar_exit(100, 103, 99, -1, 102, 96, first_bar=True) == (102, "stop")
        assert bar_exit(100, 101, 95, -1, 102, 96, first_bar=True) == (96, "target")

    def test_no_target_means_only_a_stop_can_end_it(self):
        assert bar_exit(100, 200, 99, 1, 98, None, first_bar=False) is None


class TestBracket:
    def test_a_percent_stop_and_its_target_in_r(self):
        b = bracket(ExitPlan(stop_pct=2, target_r=2, **FREE), bars((100, 100, 100, 100)) * 2, 0, 100.0, 1)
        assert (b.entry, b.dist, b.stop, b.target) == (100.0, 2.0, 98.0, 104.0)

    def test_an_atr_stop_reads_the_fifteen_bars_ending_at_the_signal(self):
        flat = [(100, 101, 99, 100)] * 20
        b = bracket(ExitPlan(stop_atr=1.5, target_r=None, **FREE), bars(*flat), 16, 100.0, 1)
        assert b.stop == pytest.approx(97.0) and b.target is None

    def test_no_room_is_none_rather_than_a_trade(self):
        """A flat series has no ATR, so an ATR stop would sit on the entry."""
        flat = [(100, 100, 100, 100)] * 20
        assert bracket(ExitPlan(stop_atr=1.5, **FREE), bars(*flat), 16, 100.0, 1) is None
        # Too early for a full ATR window is the same answer.
        assert bracket(ExitPlan(stop_atr=1.5, **FREE), bars(*flat), 2, 100.0, 1) is None

    def test_slippage_prices_the_entry_against_the_trade(self):
        assert entry_price(100.0, 1, 0.1) == pytest.approx(100.1)
        assert entry_price(100.0, -1, 0.1) == pytest.approx(99.9)

    def test_a_percent_stop_is_measured_off_the_slipped_entry(self):
        b = bracket(ExitPlan(stop_pct=2, target_r=2, fee_pct=0, slippage_pct=0.1), bars((100, 100, 100, 100)) * 2, 0, 100.0, 1)
        assert b.entry == pytest.approx(100.1) and b.dist == pytest.approx(2.002)


class TestSizing:
    def test_risk_is_a_share_of_equity_at_the_stop(self):
        # A 1% stop risking 1% of equity is a full position; half that stop is
        # twice the position, which is why the clamp below matters.
        assert notional_fraction(1.0, 1.0, 100.0) == pytest.approx(1.0)
        assert notional_fraction(1.0, 2.0, 100.0) == pytest.approx(0.5)

    def test_the_clamp_means_a_wide_stop_risks_less_than_asked(self):
        """
        No leverage, so a stop tighter than risk_pct cannot be sized up to it.
        The number a live executor must copy rather than recompute: asking for
        1% against a 0.6% stop takes 0.6% of risk, not 1%.
        """
        assert notional_fraction(1.0, 0.6, 100.0) == 1.0

    def test_caps_apply_smallest_first(self):
        assert notional_usd(1.0, 1000.0, []) == 1000.0
        assert notional_usd(1.0, 1000.0, [250.0, 500.0]) == 250.0
        assert notional_usd(0.5, 1000.0, [900.0]) == 500.0
        assert notional_usd(-1.0, 1000.0, [900.0]) == 0.0


class TestReturns:
    def test_both_swaps_pay_their_fee(self):
        entry, fill = 100.0, 104.0
        assert trade_return(entry, fill, 1, 0.0) == pytest.approx(0.04)
        assert trade_return(entry, fill, 1, 0.1) == pytest.approx(0.04 - 0.001 * (1 + 1.04))

    def test_cost_is_the_gap_to_the_frictionless_trade(self):
        ret = trade_return(100.1, 103.9, 1, 0.1)
        cost = frictionless_return(100.0, 104.0, 1) - ret
        assert cost > 0 and in_r(cost, 100.1, 2.0) == pytest.approx(cost * 100.1 / 2.0)

    def test_r_is_a_return_over_the_risk_taken(self):
        assert in_r(0.04, 100.0, 2.0) == pytest.approx(2.0)


def test_a_time_exit_holds_max_bars_then_leaves_at_the_next_open():
    assert time_exit_bar_index(entry_index=5, max_bars=1) == 6
    assert time_exit_bar_index(entry_index=5, max_bars=20) == 25


def test_every_exit_plan_field_is_either_behaviour_or_cost():
    """
    Adding a knob to ExitPlan must force a decision about whether live obeys it.
    Failing here is the point: it means someone added a field and nobody said
    which side of the parity line it falls on.
    """
    assert set(BEHAVIOURAL_FIELDS) | set(COST_FIELDS) == set(ExitPlan.model_fields)
    assert not set(BEHAVIOURAL_FIELDS) & set(COST_FIELDS)
    assert PARITY_VERSION >= 1


# ---------------------------------------------------------------------------
# The parity proof: one bar at a time reaches the same exit as the whole array.


def live_exit(candles, plan, signal_index, d):
    """
    What a monitor does: open at the next bar, then look at each closed bar as
    it arrives, holding a deadline rather than counting inside a loop. No access
    to future bars, no second pass.
    """
    entry_i = signal_index + 1
    b = bracket(plan, candles, signal_index, float(candles[entry_i]["open"]), d)
    if b is None:
        return None
    deadline = time_exit_bar_index(entry_i, plan.max_bars)
    for j in range(entry_i, len(candles)):
        bar = candles[j]
        hit = bar_exit(float(bar["open"]), float(bar["high"]), float(bar["low"]),
                       d, b.stop, b.target, first_bar=j == entry_i)
        if hit is not None:
            return j, hit[0], hit[1]
        if j >= deadline - 1:
            nxt = j + 1
            if nxt < len(candles):
                return nxt, float(candles[nxt]["open"]), "time"
            return j, float(bar["close"]), "end"
    return None


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize(
    "plan_kw",
    [
        dict(stop_atr=1.5, target_r=2.0, max_bars=20),
        dict(stop_atr=1.0, target_r=1.0, max_bars=5),
        dict(stop_pct=1.0, target_pct=2.0, max_bars=50),
        dict(stop_atr=3.0, target_r=None, max_bars=10),
    ],
)
def test_a_live_monitor_reaches_the_same_exit_as_a_replay(seed, plan_kw):
    candles = random_walk(400, seed=seed)
    plan = ExitPlan(**plan_kw, **FREE)
    checked = 0
    for signal_index in range(20, 340, 11):
        for direction, d in (("bullish", 1), ("bearish", -1)):
            sim = simulate(
                candles,
                [TapeSignal(signal_index, candles[signal_index]["time"], "s", direction, False)],
                0, len(candles), plan, "skip",
            )
            live = live_exit(candles, plan, signal_index, d)
            if not sim.trades:
                assert live is None
                continue
            t = sim.trades[0]
            assert live is not None
            assert (t.exit_index, t.reason) == (live[0], live[2])
            assert t.exit == pytest.approx(live[1])
            checked += 1
    assert checked > 40  # the parametrisation is actually exercising trades


class TestDirections:
    def test_a_signals_own_direction_wins(self):
        assert signed_direction("bullish", "skip") == 1
        assert signed_direction("bearish", "skip") == -1

    def test_a_directionless_signal_is_read_by_the_neutral_setting(self):
        assert signed_direction("neutral", "skip") is None
        assert signed_direction("neutral", "long") == 1
        assert signed_direction("neutral", "short") == -1

    def test_sides_is_about_the_venue_and_neutral_about_the_signal(self):
        """Two separate questions; a spot pool answers only the second one."""
        assert signed_direction("bearish", "skip", "long") is None
        assert signed_direction("bullish", "skip", "long") == 1
        assert signed_direction("bullish", "skip", "short") is None
        assert signed_direction("bearish", "skip", "both") == -1

    def test_tradable_is_the_one_answer_both_callers_use(self):
        assert tradable(1, "both") and tradable(-1, "both")
        assert tradable(1, "long") and not tradable(-1, "long")
        assert not tradable(1, "short") and tradable(-1, "short")
