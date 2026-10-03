"""
Candlestick shapes, on hand-built bars.

Every fixture sits in a series whose ATR is known (about 10), so the
ATR-relative floors are exercised deliberately rather than by accident.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.candles import (
    SHAPES,
    SHAPE_BIAS,
    is_bearish_engulfing,
    is_bullish_engulfing,
    is_doji,
    is_hammer,
    is_inside_bar,
    is_shooting_star,
    shape_mask,
    shape_masks,
)

UNIT = 10.0  # the ATR every single-bar test assumes


def bar(o, h, l, c, t=0):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


def series(*bars):
    """Ordinary bars (range 10) padded in front so ATR is about 10."""
    pad = [bar(100, 106, 96, 102, t=i) for i in range(20)]
    return pad + [dict(b, time=20 + i) for i, b in enumerate(bars)]


# --- doji ------------------------------------------------------------------


def test_tiny_body_is_a_doji():
    assert is_doji(bar(100.0, 105.0, 95.0, 100.5))  # body 0.5 of range 10 = 5%


def test_body_exactly_at_the_limit_counts():
    assert is_doji(bar(100.0, 110.0, 100.0, 101.0), max_body_pct=10)


def test_large_body_is_not_a_doji():
    assert not is_doji(bar(100.0, 105.0, 95.0, 104.0))


def test_zero_range_bar_is_not_a_doji():
    """Nothing traded. Calling that indecision fires rules on illiquid gaps."""
    assert not is_doji(bar(100.0, 100.0, 100.0, 100.0))


def test_direction_of_the_body_does_not_matter():
    assert is_doji(bar(100.5, 105.0, 95.0, 100.0))


# --- hammer / shooting star ------------------------------------------------


def test_hammer_has_a_long_lower_wick_and_a_small_top_body():
    # range 12, body 2 at the top, lower wick 10, no upper wick
    assert is_hammer(bar(108, 110, 98, 110), UNIT)
    assert is_hammer(bar(110, 110, 98, 108), UNIT)  # red hammer counts too


def test_hammer_needs_the_upper_wick_to_be_small():
    # lower wick 6, body 2, upper wick 6: that is a spinning top, not a hammer
    assert not is_hammer(bar(104, 112, 98, 106), UNIT)


def test_hammer_needs_a_real_range():
    """Same proportions at a tenth of the size are noise."""
    assert not is_hammer(bar(100.8, 101.0, 99.8, 101.0), UNIT)


def test_dragonfly_doji_counts_as_a_hammer():
    assert is_hammer(bar(110, 110.5, 98, 110), UNIT)


def test_shooting_star_is_the_mirror():
    assert is_shooting_star(bar(100, 112, 98, 98), UNIT)
    assert is_shooting_star(bar(98, 112, 98, 100), UNIT)
    assert not is_shooting_star(bar(108, 110, 98, 110), UNIT)  # that is the hammer


def test_hammer_and_star_are_exclusive_on_a_symmetric_bar():
    b = bar(103, 112, 96, 105)
    assert not is_hammer(b, UNIT) and not is_shooting_star(b, UNIT)


# --- engulfing ---------------------------------------------------------------


def test_bullish_engulfing_covers_the_previous_body():
    prev = bar(105, 106, 99, 100)  # down bar, body 105 -> 100
    assert is_bullish_engulfing(prev, bar(99.5, 108, 99, 106), UNIT)


def test_bullish_engulfing_must_actually_engulf():
    prev = bar(105, 106, 99, 100)
    assert not is_bullish_engulfing(prev, bar(101, 108, 99, 106), UNIT)  # opens above prev close
    assert not is_bullish_engulfing(prev, bar(99.5, 108, 99, 104), UNIT)  # closes below prev open


def test_engulfing_needs_a_real_prior_body():
    """Swallowing a one-tick body is not a reversal of anything."""
    prev = bar(100.0, 106, 96, 100.5)  # body 0.5 = 0.05 ATR
    assert not is_bullish_engulfing(prev, bar(99, 108, 98, 107), UNIT)


def test_engulfing_bar_must_itself_be_real():
    prev = bar(102, 106, 96, 100)
    assert not is_bullish_engulfing(prev, bar(99.9, 106, 96, 100.6), UNIT)  # body 0.7 = 0.07 ATR


def test_bearish_engulfing_is_the_mirror():
    prev = bar(100, 106, 99, 105)  # up bar
    assert is_bearish_engulfing(prev, bar(105.5, 106, 98, 99), UNIT)
    assert not is_bearish_engulfing(prev, bar(104, 106, 98, 99), UNIT)


def test_engulfing_requires_opposite_colours():
    prev = bar(100, 106, 99, 105)
    assert not is_bullish_engulfing(prev, bar(99, 110, 98, 108), UNIT)  # prev was up, not down


# --- inside bar --------------------------------------------------------------


def test_inside_bar_sits_within_the_mother_bar():
    mother = bar(100, 112, 96, 108)
    assert is_inside_bar(mother, bar(104, 110, 100, 102), UNIT)
    assert is_inside_bar(mother, bar(104, 112, 96, 102), UNIT)  # touching the edges still counts


def test_inside_bar_fails_if_either_side_pokes_out():
    mother = bar(100, 112, 96, 108)
    assert not is_inside_bar(mother, bar(104, 113, 100, 102), UNIT)
    assert not is_inside_bar(mother, bar(104, 110, 95, 102), UNIT)


def test_inside_bar_needs_a_real_mother_bar():
    """Otherwise every quiet stretch is a run of inside bars."""
    mother = bar(100, 101, 99, 100.5)  # range 2 = 0.2 ATR
    assert not is_inside_bar(mother, bar(100, 100.8, 99.5, 100.2), UNIT)


# --- masks -----------------------------------------------------------------


def test_shape_masks_line_up_with_bars():
    bars = series(
        bar(100, 110, 90, 108),      # plain
        bar(100, 110, 90, 100.5),    # doji
        bar(108, 110, 90, 110),      # hammer
        bar(100, 118, 98, 99),       # shooting star, and it engulfs nothing
    )
    masks = shape_masks(bars)
    n = len(bars)
    assert masks["doji"][n - 3]
    assert masks["hammer"][n - 2]
    assert masks["shooting_star"][n - 1]
    assert not masks["hammer"][n - 4]


def test_two_bar_shapes_never_fire_on_the_first_bar():
    masks = shape_masks([bar(100, 110, 90, 108), bar(107, 112, 100, 101)])
    for shape in ("bullish_engulfing", "bearish_engulfing", "inside_bar"):
        assert not masks[shape][0]


def test_single_bar_is_doji_only():
    masks = shape_masks([bar(100, 110, 90, 100.2)])
    assert masks["doji"][0]
    assert not masks["hammer"][0]  # no ATR from one bar


def test_every_shape_has_a_bias_and_a_mask():
    masks = shape_masks(series(bar(100, 110, 90, 105)))
    assert set(masks) == set(SHAPES) == set(SHAPE_BIAS)


def test_unknown_shape_is_an_error():
    with pytest.raises(ValueError):
        shape_mask([bar(1, 2, 0, 1)], "morning_star")
