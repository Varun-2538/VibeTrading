"""
Market structure: sweeps, breakouts, rejections, swings and pullbacks.

Each event is a defined geometry over closed bars. The fixtures build the
geometry by hand so every assertion is about a known bar against a known
level, with ATR held near 10.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.structure import (
    EVENTS,
    SIDES,
    breakout_at,
    event_masks,
    events_at,
    pullback,
    recent_events,
    rejection_at,
    sweep_at,
    swings,
)

UNIT = 10.0
LEVEL = 100.0


def bar(o, h, l, c, t=0):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


def zigzag(points, bars_per_leg=6, wick=1.0):
    """Closes interpolated leg by leg through `points`; wicks of `wick` either side."""
    closes = []
    for a, b in zip(points, points[1:]):
        closes += list(np.linspace(a, b, bars_per_leg, endpoint=False))
    closes.append(points[-1])
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append(bar(o, max(o, c) + wick, min(o, c) - wick, c, t=1_000 + i * 60_000))
    return out


def with_support(level=LEVEL, tests=4):
    """
    Bars that establish a support level: price bounces off `level` `tests`
    times inside a 100-110 range, so detect_levels clusters those lows.
    ATR comes out near 10.
    """
    out = []
    t = 0
    for _ in range(tests):
        for c in (104, 108, 106, 103):
            out.append(bar(c - 1, c + 4, c - 4, c, t=t)); t += 60_000
        out.append(bar(102, 106, level, 104, t=t)); t += 60_000  # the touch
    return out


# --- single-bar events --------------------------------------------------------


def test_sweep_of_lows_is_a_wick_through_and_a_close_back_above():
    assert sweep_at(bar(103, 106, 97, 104), LEVEL, UNIT) == "bullish"


def test_a_close_below_the_level_is_not_a_sweep():
    assert sweep_at(bar(103, 106, 97, 98), LEVEL, UNIT) is None


def test_a_shallow_poke_is_not_a_sweep():
    """0.15 ATR = 1.5 here; a wick to 99.5 is noise, not a hunt."""
    assert sweep_at(bar(103, 106, 99.5, 104), LEVEL, UNIT) is None


def test_a_bar_that_opened_far_below_is_a_breakout_not_a_sweep():
    assert sweep_at(bar(90, 106, 88, 104), LEVEL, UNIT) is None


def test_sweep_of_highs_is_the_mirror():
    assert sweep_at(bar(97, 103, 94, 96), LEVEL, UNIT) == "bearish"


def test_breakout_needs_prior_closes_on_the_other_side():
    bars = [bar(95, 99, 94, 96), bar(96, 99, 95, 97), bar(97, 99, 95, 98), bar(98, 104, 97, 103)]
    assert breakout_at(bars, 3, LEVEL, UNIT) == "bullish"
    bars[1] = bar(96, 102, 95, 101)  # one prior close already above
    assert breakout_at(bars, 3, LEVEL, UNIT) is None


def test_breakout_needs_to_clear_the_level():
    bars = [bar(95, 99, 94, 96), bar(96, 99, 95, 97), bar(97, 99, 95, 98), bar(98, 102, 97, 101)]
    assert breakout_at(bars, 3, LEVEL, UNIT) is None  # 101 < 100 + 2.5


def test_breakdown_is_the_mirror():
    bars = [bar(105, 106, 101, 104), bar(104, 106, 101, 103), bar(103, 106, 101, 102), bar(102, 103, 96, 97)]
    assert breakout_at(bars, 3, LEVEL, UNIT) == "bearish"


def test_rejection_is_a_long_wick_spanning_the_level():
    assert rejection_at(bar(104, 105, 97, 105), LEVEL, UNIT) == "bullish"


def test_rejection_wick_must_be_real_and_must_span_the_level():
    assert rejection_at(bar(104, 105, 101, 105), LEVEL, UNIT) is None  # wick stops above the level
    assert rejection_at(bar(104, 105, 102, 105), LEVEL, UNIT) is None  # wick 2 < 0.5 ATR


def test_bearish_rejection_is_the_mirror():
    assert rejection_at(bar(96, 103, 95, 95), LEVEL, UNIT) == "bearish"


# --- swings and pullbacks -----------------------------------------------------


def test_uptrend_reads_hh_and_hl():
    st = swings(zigzag([100, 115, 105, 120, 110, 125, 115]))
    labels = [p["label"] for p in st["points"]]
    assert "HH" in labels and "HL" in labels
    assert st["trend"] == "uptrend"


def test_downtrend_reads_lh_and_ll():
    st = swings(zigzag([125, 110, 120, 105, 115, 100, 110]))
    assert st["trend"] == "downtrend"


def test_flat_range_is_a_range():
    st = swings(zigzag([100, 110, 100, 110, 100, 110, 100]))
    assert st["trend"] == "range"


def test_pullback_in_an_uptrend_holds_the_last_hl():
    # HL at 110, HH at 125, price has come back to 118: retrace 7/15 = 0.47
    bars = zigzag([100, 115, 105, 120, 110, 125, 118])
    pb = pullback(bars, swings(bars))
    assert pb is not None
    assert pb["side"] == "bullish"
    assert 0.3 <= pb["retrace"] <= 0.7
    assert pb["holds"]["label"] == "HL"


def test_a_shallow_dip_is_not_a_pullback():
    bars = zigzag([100, 115, 105, 120, 110, 125, 124])
    assert pullback(bars, swings(bars)) is None


def test_breaking_the_hl_is_not_a_pullback():
    bars = zigzag([100, 115, 105, 120, 110, 125, 108])
    assert pullback(bars, swings(bars)) is None


# --- events against detected levels -------------------------------------------


def test_sweep_is_found_against_a_level_the_earlier_bars_established():
    bars = with_support()
    t = bars[-1]["time"] + 60_000
    bars.append(bar(103, 106, 97.5, 104, t=t))
    found = recent_events(bars, bars=1)
    assert any(e["event"] == "sweep" and e["side"] == "bullish" and abs(e["level"] - LEVEL) < 1.5 for e in found), found


def test_no_look_ahead_on_early_bars():
    """Bar 3 has no bars before it to establish a level, so it has no events."""
    bars = with_support()
    assert events_at(bars, 3, UNIT) == []


def test_event_masks_cover_every_event_and_side():
    masks = event_masks(with_support(), tail=5)
    assert set(masks) == {(e, s) for e in EVENTS for s in SIDES}
    assert all(m.dtype == bool for m in masks.values())


def test_pullback_mask_sits_on_the_newest_bar_only():
    bars = zigzag([100, 115, 105, 120, 110, 125, 118])
    masks = event_masks(bars, tail=5)
    mask = masks[("pullback", "bullish")]
    assert mask[-1] and not mask[:-1].any()
