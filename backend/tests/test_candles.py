"""Single-candle shapes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.candles import is_doji, shape_mask


def bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


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


def test_shape_mask_lines_up_with_bars():
    bars = [bar(100, 110, 90, 108), bar(100, 110, 90, 100.5), bar(100, 110, 90, 92)]
    assert shape_mask(bars, "doji").tolist() == [False, True, False]


def test_unknown_shape_is_an_error():
    with pytest.raises(ValueError):
        shape_mask([bar(1, 2, 0, 1)], "hammer")
