"""
Ordered sequence matching over closed candles.

Candle series are built so the RSI path is controllable: a long decline drives
RSI well below 30, then a sharp rise crosses it back above on a known bar.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.indicators import crosses, rsi
from analysis.sequence import describe_steps, match_sequence, step_mask

DOJI = {"type": "candle", "shape": "doji", "max_body_pct": 10}
RSI_UP = {"type": "indicator", "indicator": "rsi", "period": 14, "cross": "above", "level": 30}


def bars(closes, doji_at=()):
    """
    Each bar closes at `closes[i]`. Normal bars have a body of most of their
    range; bars listed in `doji_at` have almost no body.
    """
    out = []
    for i, c in enumerate(closes):
        if i in doji_at:
            o = c - 0.01
        else:
            o = c - 2.0
        out.append({"time": 1_700_000_000_000 + i * 60_000, "open": o, "high": c + 3, "low": o - 3, "close": c, "volume": 1})
    return out


def declining_then_rising(fall=40, rise=8):
    """RSI sinks under 30 over the fall, then crosses back above on the rise."""
    closes = list(np.linspace(200, 120, fall)) + list(np.linspace(121, 140, rise))
    return closes


def cross_index(closes):
    mask = crosses(rsi(np.array(closes), 14), 30, "above")
    hits = np.flatnonzero(mask)
    assert len(hits) >= 1, "fixture must contain a cross"
    return int(hits[-1])


def test_fixture_actually_crosses():
    closes = declining_then_rising()
    assert cross_index(closes) > 40


def test_doji_then_cross_matches_when_cross_is_the_last_bar():
    closes = declining_then_rising()
    x = cross_index(closes)
    series = bars(closes[: x + 1], doji_at={x - 2})
    assert match_sequence(series, [DOJI, RSI_UP], within_bars=3) == [x - 2, x]


def test_no_match_when_the_cross_is_not_on_the_last_bar():
    """A sequence that completed three bars ago is history, not a signal."""
    closes = declining_then_rising()
    x = cross_index(closes)
    series = bars(closes[: x + 4], doji_at={x - 2})
    assert match_sequence(series, [DOJI, RSI_UP], within_bars=3) is None


def test_no_match_when_the_doji_is_outside_the_window():
    closes = declining_then_rising()
    x = cross_index(closes)
    series = bars(closes[: x + 1], doji_at={x - 5})
    assert match_sequence(series, [DOJI, RSI_UP], within_bars=3) is None
    assert match_sequence(series, [DOJI, RSI_UP], within_bars=5) == [x - 5, x]


def test_steps_must_be_in_order():
    """A doji on the same bar as the cross is not 'doji then cross'."""
    closes = declining_then_rising()
    x = cross_index(closes)
    series = bars(closes[: x + 1], doji_at={x})
    assert match_sequence(series, [DOJI, RSI_UP], within_bars=3) is None


def test_nearest_doji_is_chosen_when_several_qualify():
    closes = declining_then_rising()
    x = cross_index(closes)
    series = bars(closes[: x + 1], doji_at={x - 3, x - 1})
    assert match_sequence(series, [DOJI, RSI_UP], within_bars=3) == [x - 1, x]


def test_single_step_sequence_is_just_the_shape_on_the_last_bar():
    series = bars([100, 101, 102], doji_at={2})
    assert match_sequence(series, [DOJI]) == [2]
    assert match_sequence(bars([100, 101, 102], doji_at={1}), [DOJI]) is None


def test_empty_steps_or_short_series_never_match():
    assert match_sequence(bars([1, 2, 3]), []) is None
    assert match_sequence(bars([1]), [DOJI, RSI_UP]) is None


def test_step_mask_rejects_unknown_kinds():
    import pytest

    with pytest.raises(ValueError):
        step_mask(bars([1, 2]), {"type": "volume"})
    with pytest.raises(ValueError):
        step_mask(bars([1, 2]), {"type": "indicator", "indicator": "macd", "level": 0, "cross": "above"})


def test_describe_steps_reads_naturally():
    assert describe_steps([DOJI, RSI_UP]) == "doji, then RSI(14) crosses above 30"
