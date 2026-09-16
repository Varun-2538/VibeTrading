"""
Candle history for backtests: how deep, where from, and how it is kept current.

Kept apart from CandleService on purpose. CandleService serves the chart the
latest 1000 bars through Redis; this fills a table years deep, page by page,
and must survive Binance rate limits and restarts halfway through. The SQL
lives in repositories.history_repository; everything here is testable without
a database.
"""
from typing import Any, Dict, List, Optional, Tuple

PAIRS: Tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT",
)

TIMEFRAME_MS: Dict[str, int] = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

# How far back each timeframe is kept. Sized so the slowest replay (patterns)
# stays under ~30 minutes on the production e2-small; None keeps everything
# Binance has.
HISTORY_DEPTH_DAYS: Dict[str, Optional[int]] = {
    "5m": 183,
    "15m": 365,
    "1h": 1095,
    "1d": None,
}

DAY_MS = 24 * 60 * 60_000


class UnknownHistoryTimeframe(ValueError):
    """A timeframe the history store does not keep."""


def _step(timeframe: str) -> int:
    try:
        return TIMEFRAME_MS[timeframe]
    except KeyError:
        raise UnknownHistoryTimeframe(
            f"No history is kept for '{timeframe}'. Expected one of: {', '.join(TIMEFRAME_MS)}"
        )


def depth_start_ms(timeframe: str, now_ms: int) -> int:
    """The earliest bar open time to keep, aligned to the timeframe."""
    step = _step(timeframe)
    days = HISTORY_DEPTH_DAYS[timeframe]
    if days is None:
        return 0
    start = now_ms - days * DAY_MS
    return start - (start % step)


def parse_klines(rows: List[List[Any]], now_ms: int) -> List[Dict[str, Any]]:
    """
    Binance kline rows to candles, dropping the bar still forming.

    A bar is closed when its close time (row[6]) is before now. Storing a
    forming bar would bake a price that later changes into history a backtest
    trusts.
    """
    return [
        {
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in rows
        if int(row[6]) < now_ms
    ]


def missing_bars(first_ms: int, last_ms: int, bars: int, timeframe: str) -> int:
    """Bars that should exist between first and last inclusive but do not."""
    if bars == 0:
        return 0
    expected = (last_ms - first_ms) // _step(timeframe) + 1
    return max(0, expected - bars)
