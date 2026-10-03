"""Turning a tape into the fires the live engine would have produced."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.signals import distinct_setups, signals_from_tape
from walks import H, T0


def bars(n):
    return [{"time": T0 + i * H, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0} for i in range(n)]


def row(i, *cands):
    return [i, [list(c) for c in cands]]


SEQ = {"agent": "sequence"}


def run(tape, params=SEQ, persist=0, cooldown=0, n=10):
    return signals_from_tape(tape, bars(n), params, timeframe_ms=H, persist_bars=persist,
                             cooldown_secs=cooldown, start=0, end=n)


def test_every_candidate_bar_fires_without_persistence_or_cooldown():
    tape = [row(2, ("a", "bullish", False, None, None)), row(3, ("b", "bearish", False, None, None))]
    assert [(s.index, s.identity, s.direction) for s in run(tape)] == [(2, "a", "bullish"), (3, "b", "bearish")]
    assert run(tape)[0].time == T0 + 2 * H


def test_persistence_delays_the_fire_by_a_bar():
    tape = [row(i, ("a", "bullish", False, None, None)) for i in (2, 3, 4)]
    assert [s.index for s in run(tape, persist=1)] == [3, 4]


def test_cooldown_runs_on_bar_close_times():
    tape = [row(i, ("a", "bullish", False, None, None)) for i in range(0, 6)]
    # Fired at bar 0 close (T0+1h). Bar 1 closes at T0+2h: 3600s < 7200s. Bar 2 at T0+3h: fires.
    assert [s.index for s in run(tape, cooldown=7200)] == [0, 2, 4]


def test_the_filter_picks_the_first_candidate_that_passes():
    params = {"agent": "pattern", "min_confidence": 70}
    tape = [row(1, ("weak", "bearish", False, 50.0, None), ("good", "bullish", False, 80.0, None))]
    assert [s.identity for s in run(tape, params)] == ["good"]
    assert run([row(1, ("weak", "bearish", False, 50.0, None))], params) == []


def test_distinct_setups_keep_the_first_fire_of_each():
    tape = [row(i, ("a", "bullish", False, None, None)) for i in (1, 2, 3)] + [row(5, ("b", "bearish", False, None, None))]
    assert [(s.index, s.identity) for s in distinct_setups(run(tape))] == [(1, "a"), (5, "b")]
