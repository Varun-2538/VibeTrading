"""The signal study: arithmetic, the unseen boundary, the baseline, honesty."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.signals import TapeSignal
from backtest.study import MIN_SIGNALS, period_study, signed, study
from walks import H, T0, random_walk


def trend(n, step=0.01):
    """Closes rising by `step` (1%) every bar."""
    out, price = [], 100.0
    for i in range(n):
        nxt = price * (1 + step)
        out.append({"time": T0 + i * H, "open": price, "high": nxt * 1.001, "low": price * 0.999, "close": nxt, "volume": 1.0})
        price = nxt
    return out


def sig(i, direction="bullish"):
    return TapeSignal(i, T0 + i * H, f"s{i}", direction, False)


def h(period, horizon):
    return next(x for x in period["horizons"] if x["h"] == horizon)


def test_signed_directions():
    assert signed("bullish", "skip") == 1 and signed("bearish", "skip") == -1
    assert signed("neutral", "skip") is None and signed("neutral", "short") == -1


def test_forward_return_is_signed_by_direction():
    candles = trend(100)
    up = period_study(candles, [sig(10)], 0, 100, "skip")
    down = period_study(candles, [sig(10, "bearish")], 0, 100, "skip")
    assert h(up, 1)["mean_pct"] == 1.0
    assert h(down, 1)["mean_pct"] == -1.0


def test_baseline_follows_the_direction_mix():
    candles = trend(100)
    shorts = period_study(candles, [sig(i, "bearish") for i in range(0, 60, 3)], 0, 100, "skip")
    assert h(shorts, 1)["baseline_pct"] == -1.0
    assert h(shorts, 1)["edge_pct"] == 0.0


def test_a_seen_horizon_never_reads_past_the_split():
    candles = trend(100)
    report = study(candles, [sig(45)], start=0, split=50, end=100, neutral="skip")
    assert h(report["seen"], 1)["signals"] == 1
    assert h(report["seen"], 10)["signals"] == 0
    assert report["unseen"]["signals"] == 0


def test_neutral_signals_are_skipped_or_directed():
    candles = trend(100)
    skipped = period_study(candles, [sig(5, "neutral")], 0, 100, "skip")
    longed = period_study(candles, [sig(5, "neutral")], 0, 100, "long")
    assert skipped["signals"] == 0 and skipped["skipped_neutral"] == 1
    assert longed["signals"] == 1


def test_excursions_are_in_atr_units():
    candles = trend(100)
    p = period_study(candles, [sig(30)], 0, 100, "skip")
    assert p["mfe_atr"] > 0 and p["mae_atr"] < p["mfe_atr"]


def test_confidence_interval_is_reproducible_and_brackets_the_edge():
    candles = random_walk(1500, seed=4)
    signals = [sig(i, "bullish" if i % 2 else "bearish") for i in range(20, 1400, 9)]
    a = period_study(candles, signals, 0, 1500, "skip")
    b = period_study(candles, signals, 0, 1500, "skip")
    assert a == b
    head = h(a, 10)
    assert head["ci_pct"][0] <= head["edge_pct"] <= head["ci_pct"][1]


def test_few_signals_are_flagged():
    p = period_study(trend(100), [sig(3)], 0, 100, "skip")
    assert "too_few_signals" in p["flags"] and p["signals"] < MIN_SIGNALS


def test_random_signals_on_random_walks_rarely_claim_an_edge():
    claimed = 0
    for seed in range(20):
        candles = random_walk(3000, seed=100 + seed)
        rng = np.random.default_rng(seed)
        signals = [sig(i, "bullish" if rng.random() < 0.5 else "bearish") for i in range(30, 2900, 23)]
        if "no_edge_detected" not in period_study(candles, signals, 0, 3000, "skip")["flags"]:
            claimed += 1
    # A 95% interval should wrongly exclude zero about once in twenty.
    assert claimed <= 3


def test_nothing_non_finite_reaches_the_report():
    p = period_study(trend(30), [], 0, 30, "skip")
    assert p["signals"] == 0 and h(p, 10)["mean_pct"] is None and h(p, 10)["ci_pct"] is None
    assert "no_edge_detected" in p["flags"]
