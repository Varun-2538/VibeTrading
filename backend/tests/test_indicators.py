"""Indicator series and cross detection. Pure numpy, no I/O."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.indicators import crosses, ema, macd, rsi


def test_rsi_warm_up_is_nan_not_zero():
    """Zero would read as 'deeply oversold' and could trigger a cross."""
    out = rsi(np.linspace(100, 110, 30), period=14)
    assert np.all(np.isnan(out[:14]))
    assert not np.any(np.isnan(out[14:]))


def test_rsi_pins_at_100_on_a_pure_uptrend():
    out = rsi(np.linspace(100, 130, 40), period=14)
    assert out[-1] == 100.0


def test_rsi_is_zero_on_a_pure_downtrend():
    out = rsi(np.linspace(130, 100, 40), period=14)
    assert out[-1] == pytest.approx(0.0, abs=1e-9)


def test_rsi_matches_a_hand_computed_reference():
    """
    Wilder's RSI on the classic 14-period reference series. The expected value
    is what the textbook (and every charting platform) prints for this data.
    """
    closes = np.array([
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
        45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
    ])
    out = rsi(closes, period=14)
    assert out[14] == pytest.approx(70.46, abs=0.05)


def _previous_rsi(prices, period=14):
    """
    The implementation that lived in MarketDataService before the move, kept
    verbatim as an independent reference. Its warm-up region was zeros.
    """
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gains = np.zeros(len(prices))
    avg_losses = np.zeros(len(prices))
    avg_gains[period] = np.mean(gains[:period])
    avg_losses[period] = np.mean(losses[:period])
    for i in range(period + 1, len(prices)):
        avg_gains[i] = (avg_gains[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_losses[i] = (avg_losses[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = avg_gains / (avg_losses + 1e-10)
    return 100 - (100 / (1 + rs))


def test_rsi_agrees_with_the_implementation_it_replaced():
    """Moving the math must not change what the chat has been reporting."""
    rng = np.random.default_rng(7)
    closes = 100 + np.cumsum(rng.normal(0, 1, 200))
    ours = rsi(closes, period=14)
    theirs = _previous_rsi(closes, period=14)
    np.testing.assert_allclose(ours[14:], theirs[14:], atol=1e-6)


def test_rsi_too_short_is_all_nan():
    assert np.all(np.isnan(rsi(np.arange(10.0), period=14)))


def test_ema_seeds_with_the_sma():
    prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    out = ema(prices, period=3)
    assert np.all(np.isnan(out[:2]))
    assert out[2] == pytest.approx(2.0)


def test_macd_signal_is_not_poisoned_by_warm_up():
    """Seeding the signal EMA at index 0 would carry NaN through every value."""
    line, signal, hist = macd(np.linspace(100, 120, 80))
    assert not np.isnan(signal[-1])
    assert not np.isnan(hist[-1])


# --- crosses ---------------------------------------------------------------


def test_cross_above_fires_on_the_bar_that_reaches_the_level():
    s = np.array([20.0, 25.0, 29.9, 30.0, 35.0])
    assert crosses(s, 30, "above").tolist() == [False, False, False, True, False]


def test_cross_below_is_the_mirror():
    s = np.array([80.0, 75.0, 70.0, 65.0])
    assert crosses(s, 70, "below").tolist() == [False, False, True, False]


def test_sitting_on_the_level_is_not_a_cross():
    s = np.array([30.0, 30.0, 30.0])
    assert not crosses(s, 30, "above").any()


def test_nan_warm_up_never_registers_a_cross():
    s = np.array([np.nan, np.nan, 35.0, 36.0])
    assert not crosses(s, 30, "above").any()


def test_unknown_direction_is_an_error():
    with pytest.raises(ValueError):
        crosses(np.array([1.0, 2.0]), 1.5, "sideways")
