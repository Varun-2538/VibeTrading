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
INDICATORS = ("rsi", "ema", "macd", "stochastic", "bollinger", "vwap", "volume", "atr")


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


def sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average, NaN until there are `period` values."""
    values = np.asarray(values, dtype=float)
    out = np.full(values.shape, np.nan)
    if period <= 0 or values.size < period:
        return out
    window = np.convolve(values, np.ones(period) / period, mode="valid")
    out[period - 1:] = window
    return out


def stochastic(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    k_period: int = 14,
    k_smooth: int = 3,
    d_period: int = 3,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Smoothed %K and its %D average.

    %K is where the close sits inside the highest high and lowest low of the
    last k_period bars. A range of zero has no position to report, so it stays
    NaN rather than being called 50 or 100.
    """
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    raw = np.full(closes.shape, np.nan)

    for i in range(k_period - 1, closes.size):
        window = slice(i + 1 - k_period, i + 1)
        top, bottom = highs[window].max(), lows[window].min()
        if top > bottom:
            raw[i] = (closes[i] - bottom) / (top - bottom) * 100.0

    k = raw if k_smooth <= 1 else sma(raw, k_smooth)
    return k, sma(k, d_period)


def bollinger(
    closes: np.ndarray,
    period: int = 20,
    std: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Middle, upper, lower band and bandwidth, as fractions of the middle."""
    closes = np.asarray(closes, dtype=float)
    middle = sma(closes, period)
    deviation = np.full(closes.shape, np.nan)
    for i in range(period - 1, closes.size):
        deviation[i] = closes[i + 1 - period: i + 1].std()
    upper = middle + std * deviation
    lower = middle - std * deviation
    with np.errstate(divide="ignore", invalid="ignore"):
        width = (upper - lower) / middle
    return middle, upper, lower, width


WEEK_MS = 7 * 86_400_000
DAY_MS = 86_400_000
# 1970-01-01 was a Thursday, so Monday is four days in.
WEEK_OFFSET_MS = 4 * DAY_MS


def _session(times: np.ndarray, anchor: str) -> np.ndarray:
    times = np.asarray(times, dtype=np.int64)
    if anchor == "week":
        return (times + WEEK_OFFSET_MS) // WEEK_MS
    return times // DAY_MS


def vwap(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    times: np.ndarray,
    anchor: str = "day",
) -> np.ndarray:
    """
    Volume-weighted average price since the session opened.

    Crypto never closes, so "the session" is a clock convention: the UTC day,
    or the week beginning Monday - the same anchors charting tools default to.
    Typical price (high, low, close averaged) is the classic weight.
    """
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    typical = (highs + lows + closes) / 3.0
    sessions = _session(times, anchor)

    out = np.full(closes.shape, np.nan)
    price_volume = 0.0
    volume = 0.0
    current = None
    for i in range(closes.size):
        if sessions[i] != current:
            current, price_volume, volume = sessions[i], 0.0, 0.0
        price_volume += typical[i] * volumes[i]
        volume += volumes[i]
        out[i] = price_volume / volume if volume > 0 else typical[i]
    return out


def volume_ratio(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    """This bar's volume over the average of the `period` bars before it."""
    volumes = np.asarray(volumes, dtype=float)
    average = sma(volumes, period)
    out = np.full(volumes.shape, np.nan)
    if volumes.size > period:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[period:] = volumes[period:] / average[period - 1: -1]
        out[np.isinf(out)] = np.nan
    return out


def true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """True range, NaN on the first bar - it has no previous close."""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    out = np.full(highs.shape, np.nan)
    if highs.size < 2:
        return out
    previous = closes[:-1]
    out[1:] = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - previous), np.abs(lows[1:] - previous)),
    )
    return out


def atr_series(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """
    Average true range of the bars *before* each bar.

    Excluding the current bar is what lets a threshold ask "is this bar bigger
    than what came before it" without the bar inflating its own benchmark.
    """
    ranges = true_range(highs, lows, closes)
    average = sma(ranges, period)
    out = np.full(ranges.shape, np.nan)
    if ranges.size > 1:
        out[1:] = average[:-1]
    return out


def crosses_series(a: np.ndarray, b: np.ndarray, direction: str) -> np.ndarray:
    """
    True on the bar where `a` crossed `b`.

    Strict on both sides: it must have been on the other side before and be
    beyond it now, so a series resting exactly on the other never signals.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    out = np.zeros(a.shape, dtype=bool)
    if a.size < 2:
        return out
    before, now = a[:-1] - b[:-1], a[1:] - b[1:]
    valid = ~(np.isnan(before) | np.isnan(now))
    if direction == "above":
        out[1:] = valid & (before <= 0) & (now > 0)
    else:
        out[1:] = valid & (before >= 0) & (now < 0)
    return out
