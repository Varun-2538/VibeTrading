"""
Indicator series over closed candles. Pure numpy, no I/O.

Moved here from MarketDataService so the rule engine and the tests can use the
same arithmetic the chat reports, rather than a second implementation that
drifts. Every function returns a full series aligned to the input, with the
warm-up region filled with NaN so a caller cannot mistake "not computed yet"
for a real value of zero.
"""
from typing import Tuple

import numpy as np

# Indicators the rule vocabulary knows. Adding one is: a function here, a name
# in this tuple, and a case in analysis/sequence.py.
INDICATORS = ("rsi",)


def rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """
    Wilder's RSI.

    Seeded with a simple average over the first `period` changes and smoothed
    from there, which is the textbook definition and matches what charting
    platforms draw. Indices before `period` are NaN.
    """
    prices = np.asarray(prices, dtype=float)
    out = np.full(len(prices), np.nan)
    if len(prices) <= period:
        return out

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    out[period] = _rsi_value(avg_gain, avg_loss)

    for i in range(period + 1, len(prices)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = _rsi_value(avg_gain, avg_loss)

    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    # No losses at all means RSI pins at 100; the epsilon would otherwise put
    # it a hair under, and a cross of 100 could never be observed.
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def ema(prices: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average, seeded with the SMA of the first `period`."""
    prices = np.asarray(prices, dtype=float)
    out = np.full(len(prices), np.nan)
    if len(prices) < period:
        return out

    multiplier = 2.0 / (period + 1)
    out[period - 1] = float(np.mean(prices[:period]))
    for i in range(period, len(prices)):
        out[i] = (prices[i] - out[i - 1]) * multiplier + out[i - 1]
    return out


def macd(
    prices: np.ndarray,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD line, signal line, histogram."""
    fast = ema(prices, fast_period)
    slow = ema(prices, slow_period)
    line = fast - slow
    # The signal EMA is seeded where the MACD line first exists, not at index
    # 0, otherwise the NaN warm-up poisons every later value.
    first = int(np.argmax(~np.isnan(line))) if np.any(~np.isnan(line)) else len(line)
    signal = np.full(len(prices), np.nan)
    if first < len(line):
        signal[first:] = ema(line[first:], signal_period)
    return line, signal, line - signal


def crosses(series: np.ndarray, level: float, direction: str) -> np.ndarray:
    """
    Boolean mask: True at each index where `series` crossed `level`.

    "above" means the previous value was below the level and this one is at or
    above it; "below" is the mirror. Any comparison involving NaN is False, so
    the warm-up region never registers a cross.
    """
    series = np.asarray(series, dtype=float)
    out = np.zeros(len(series), dtype=bool)
    if len(series) < 2:
        return out

    prev, curr = series[:-1], series[1:]
    with np.errstate(invalid="ignore"):
        if direction == "above":
            hit = (prev < level) & (curr >= level)
        elif direction == "below":
            hit = (prev > level) & (curr <= level)
        else:
            raise ValueError(f"direction must be 'above' or 'below', got {direction!r}")
    out[1:] = hit & ~np.isnan(prev) & ~np.isnan(curr)
    return out
