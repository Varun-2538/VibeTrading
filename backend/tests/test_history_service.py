"""History store: depths, parsing, gap counting, paging, resume, retry."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import history_service as hs

DAY = 86_400_000
NOW = 1_780_000_000_000  # fixed "now" for every test


def kline(open_ms, step_ms, price=100.0):
    """A Binance kline row: strings for prices, close time = open + step - 1."""
    return [
        open_ms, str(price), str(price + 2), str(price - 2), str(price + 1), "12.5",
        open_ms + step_ms - 1, "0", 0, "0", "0", "0",
    ]


def test_depths_match_the_spec():
    assert hs.HISTORY_DEPTH_DAYS == {"5m": 183, "15m": 365, "1h": 1095, "1d": None}
    assert set(hs.TIMEFRAME_MS) == set(hs.HISTORY_DEPTH_DAYS)
    assert len(hs.PAIRS) == 9


def test_depth_start_is_aligned_to_the_timeframe():
    start = hs.depth_start_ms("1h", NOW)
    assert start % hs.TIMEFRAME_MS["1h"] == 0
    assert NOW - start >= 1095 * DAY
    assert NOW - start < 1095 * DAY + hs.TIMEFRAME_MS["1h"]


def test_unlimited_depth_starts_at_zero():
    assert hs.depth_start_ms("1d", NOW) == 0


def test_unknown_timeframe_is_refused():
    with pytest.raises(hs.UnknownHistoryTimeframe):
        hs.depth_start_ms("1m", NOW)


def test_parse_klines_coerces_and_keeps_only_closed_bars():
    step = hs.TIMEFRAME_MS["1h"]
    last_open = NOW - (NOW % step)  # the bar still forming at NOW
    rows = [kline(last_open - step, step), kline(last_open, step)]
    candles = hs.parse_klines(rows, NOW)
    assert candles == [{
        "time": last_open - step, "open": 100.0, "high": 102.0, "low": 98.0,
        "close": 101.0, "volume": 12.5,
    }]


def test_missing_bars_counts_holes_between_first_and_last():
    step = hs.TIMEFRAME_MS["15m"]
    assert hs.missing_bars(0, 9 * step, 10, "15m") == 0
    assert hs.missing_bars(0, 9 * step, 7, "15m") == 3
    assert hs.missing_bars(0, 0, 0, "15m") == 0
