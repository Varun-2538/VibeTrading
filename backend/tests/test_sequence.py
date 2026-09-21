"""
Ordered sequence matching over closed candles.

Candle series are built so the RSI path is controllable: a long decline drives
RSI well below 30, then a sharp rise crosses it back above on a known bar.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

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


from analysis.sequence import step_mask

H = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)  # a UTC midnight


def ohlcv(rows, step_ms=H, start=T0):
    """rows: (open, high, low, close, volume)."""
    return [
        {"time": start + i * step_ms, "open": o, "high": h, "low": l, "close": c, "volume": v}
        for i, (o, h, l, c, v) in enumerate(rows)
    ]


def rising_rows(n, start=100.0, step=1.0, volume=10.0):
    return [(start + i * step, start + i * step + 0.4, start + i * step - 0.4, start + i * step + 0.2, volume)
            for i in range(n)]


def test_ema_cross_fires_once_when_the_fast_line_crosses_up():
    # Falling then rising hard: the fast EMA must cross the slow one exactly once.
    rows = [(100 - i, 100 - i + 0.3, 100 - i - 0.3, 100 - i, 10.0) for i in range(40)]
    rows += [(60 + 4 * i, 60 + 4 * i + 1, 60 + 4 * i - 1, 62 + 4 * i, 10.0) for i in range(30)]
    mask = step_mask(ohlcv(rows), {"type": "ema_cross", "fast": 5, "slow": 20, "cross": "above"})
    assert mask.sum() == 1 and mask[:20].sum() == 0


def test_macd_cross_can_watch_the_signal_line_or_zero():
    rows = [(100 - i, 100 - i + 0.3, 100 - i - 0.3, 100 - i, 10.0) for i in range(60)]
    rows += [(40 + 3 * i, 40 + 3 * i + 1, 40 + 3 * i - 1, 42 + 3 * i, 10.0) for i in range(60)]
    candles = ohlcv(rows)
    signal = step_mask(candles, {"type": "macd_cross", "against": "signal", "cross": "above"})
    zero = step_mask(candles, {"type": "macd_cross", "against": "zero", "cross": "above"})
    assert signal.any() and zero.any()
    # Crossing the signal line leads crossing zero.
    assert int(np.argmax(signal)) < int(np.argmax(zero))


def test_stochastic_crosses_a_level_and_its_d_line():
    rows = [(100.0, 110.0, 90.0, 92.0, 10.0)] * 20 + [(100.0, 110.0, 90.0, 108.0, 10.0)] * 5
    candles = ohlcv(rows)
    level = step_mask(candles, {"type": "stoch_cross", "against": "level", "level": 80, "cross": "above"})
    against_d = step_mask(candles, {"type": "stoch_cross", "against": "d", "cross": "above"})
    assert level.any() and against_d.any()


def test_bollinger_band_cross_and_squeeze():
    quiet = [(100.0, 100.2, 99.8, 100.0, 10.0)] * 60
    breakout = [(100.0, 106.0, 99.9, 105.0, 10.0)]
    candles = ohlcv(quiet + breakout)
    upper = step_mask(candles, {"type": "bollinger", "band": "upper", "cross": "above", "period": 20})
    assert upper[-1] and upper[:-1].sum() == 0
    squeeze = step_mask(candles, {"type": "bollinger_squeeze", "period": 20, "lookback": 25})
    assert squeeze[:-1].any() and not squeeze[-1]


def test_vwap_cross_uses_the_session_anchor():
    # A day of weak closes, then a strong one that lifts the close over VWAP.
    rows = [(100.0, 100.5, 99.5, 99.6, 10.0)] * 5 + [(99.6, 103.0, 99.5, 102.5, 10.0)]
    mask = step_mask(ohlcv(rows), {"type": "vwap_cross", "anchor": "day", "cross": "above"})
    assert mask[-1]


def test_volume_spike_needs_the_multiple_and_takes_no_direction_of_its_own():
    rows = rising_rows(21) + [(120.0, 121.0, 119.0, 120.5, 100.0)]
    mask = step_mask(ohlcv(rows), {"type": "volume_spike", "multiple": 2.0, "period": 20})
    assert mask[-1] and mask[:-1].sum() == 0


def test_atr_expansion_fires_on_an_unusually_wide_bar():
    rows = [(100.0, 100.5, 99.5, 100.0, 10.0)] * 20 + [(100.0, 110.0, 99.0, 109.0, 10.0)]
    mask = step_mask(ohlcv(rows), {"type": "atr_expansion", "multiple": 2.0, "period": 14})
    assert mask[-1] and mask[:-1].sum() == 0


def test_an_unknown_step_type_is_refused_loudly():
    # A typo in a step must not read as "never matches", which would look
    # like a rule that simply never fires.
    with pytest.raises(ValueError, match="Unknown step type"):
        step_mask(ohlcv(rising_rows(30)), {"type": "nonsense"})
