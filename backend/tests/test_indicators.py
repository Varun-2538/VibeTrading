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


import numpy as np

from analysis import indicators as ind

DAY = 86_400_000
HOUR = 3_600_000


def test_sma_warms_up_with_nan():
    out = ind.sma(np.array([1.0, 2, 3, 4]), 3)
    assert np.isnan(out[:2]).all()
    assert out[2] == 2.0 and out[3] == 3.0


def test_stochastic_reads_position_in_the_range():
    # Closes climb to the top of a 0-10 range, so %K ends at 100.
    highs = np.array([10.0] * 6)
    lows = np.array([0.0] * 6)
    closes = np.array([5.0, 5, 5, 10, 10, 10])
    k, d = ind.stochastic(highs, lows, closes, k_period=3, k_smooth=1, d_period=3)
    assert np.isnan(k[:2]).all()
    assert k[2] == 50.0 and k[5] == 100.0
    assert d[5] == pytest.approx(100.0) and np.isnan(d[3])


def test_stochastic_on_a_flat_range_is_not_a_division_by_zero():
    flat = np.array([5.0] * 5)
    k, _ = ind.stochastic(flat, flat, flat, k_period=3, k_smooth=1, d_period=3)
    assert np.isnan(k[2:]).all() or (k[2:] == 50.0).all()


def test_bollinger_bands_are_symmetric_about_the_mean():
    closes = np.array([1.0, 2, 3, 4, 5, 6])
    mid, up, low, width = ind.bollinger(closes, period=3, std=2.0)
    assert np.isnan(mid[:2]).all()
    assert mid[2] == 2.0
    spread = np.std(np.array([1.0, 2, 3]))
    assert up[2] == 2.0 + 2 * spread and low[2] == 2.0 - 2 * spread
    assert width[2] == (up[2] - low[2]) / mid[2]


def test_vwap_resets_each_utc_day():
    times = np.array([0, HOUR, DAY, DAY + HOUR])
    price = np.array([10.0, 20.0, 100.0, 200.0])
    volumes = np.array([1.0, 1.0, 1.0, 1.0])
    out = ind.vwap(price, price, price, volumes, times, anchor="day")
    assert out[0] == 10.0 and out[1] == 15.0  # first day accumulates
    assert out[2] == 100.0 and out[3] == 150.0  # second day starts again


def test_vwap_weighs_by_volume_and_uses_typical_price():
    times = np.array([0, HOUR])
    highs, lows, closes = np.array([12.0, 22.0]), np.array([8.0, 18.0]), np.array([10.0, 20.0])
    out = ind.vwap(highs, lows, closes, np.array([1.0, 3.0]), times, anchor="day")
    assert out[0] == 10.0
    assert out[1] == (10.0 * 1 + 20.0 * 3) / 4


def test_vwap_can_anchor_to_the_week():
    # 1970-01-01 was a Thursday; the week boundary is Monday 1970-01-05.
    times = np.array([0, 4 * DAY, 4 * DAY + HOUR])
    price = np.array([10.0, 100.0, 200.0])
    out = ind.vwap(price, price, price, np.array([1.0, 1.0, 1.0]), times, anchor="week")
    assert out[0] == 10.0 and out[1] == 100.0 and out[2] == 150.0


def test_volume_ratio_compares_with_the_bars_before():
    volumes = np.array([10.0, 10, 10, 30])
    out = ind.volume_ratio(volumes, period=3)
    assert np.isnan(out[:3]).all()
    assert out[3] == 3.0


def test_true_range_accounts_for_gaps():
    highs = np.array([10.0, 20.0])
    lows = np.array([9.0, 19.0])
    closes = np.array([9.5, 19.5])
    tr = ind.true_range(highs, lows, closes)
    assert np.isnan(tr[0])
    assert tr[1] == 20.0 - 9.5


def test_atr_series_excludes_the_bar_it_labels():
    highs = np.array([10.0, 11, 12, 40])
    lows = np.array([9.0, 10, 11, 10])
    closes = np.array([9.5, 10.5, 11.5, 39.0])
    atr = ind.atr_series(highs, lows, closes, period=2)
    assert np.isnan(atr[:2]).all()
    assert atr[3] == np.mean([11.0 - 9.5, 12.0 - 10.5])


def test_crosses_series_needs_a_real_crossing():
    a = np.array([1.0, 2.0, 3.0, 1.0])
    b = np.array([2.0, 2.0, 2.0, 2.0])
    above = ind.crosses_series(a, b, "above")
    below = ind.crosses_series(a, b, "below")
    assert not above[0] and not above[1]  # touching is not crossing
    assert above[2] and not above[3]
    assert below[3] and not below[:3].any()
    # Coming to rest exactly on the line is not a cross either.
    level = ind.crosses_series(np.array([3.0, 2.0]), np.array([2.0, 2.0]), "below")
    assert not level.any()


def test_crosses_series_is_false_wherever_an_input_is_nan():
    a = np.array([np.nan, 1.0, 3.0])
    b = np.array([2.0, 2.0, 2.0])
    assert not ind.crosses_series(a, b, "above")[:2].any()
    assert ind.crosses_series(a, b, "above")[2]


def test_indicator_names_cover_the_new_triggers():
    assert ind.INDICATORS == ("rsi", "ema", "macd", "stochastic", "bollinger", "vwap", "volume", "atr")


def test_rolling_min_tracks_the_window_and_ignores_nan():
    values = np.array([np.nan, 5.0, 3.0, 4.0, 9.0, 9.0])
    out = ind.rolling_min(values, 3)
    assert np.isnan(out[0])
    assert list(out[1:]) == [5.0, 3.0, 3.0, 3.0, 4.0]


def test_rolling_min_matches_the_naive_version():
    rng = np.random.default_rng(3)
    values = rng.normal(size=200)
    values[::17] = np.nan
    fast = ind.rolling_min(values, 20)
    for i in range(values.size):
        window = values[max(0, i - 19): i + 1]
        if np.isnan(window).all():
            assert np.isnan(fast[i])
        else:
            assert fast[i] == pytest.approx(np.nanmin(window))
