"""
Candle history for backtests: how deep, where from, and how it is kept current.

Kept apart from CandleService on purpose. CandleService serves the chart the
latest 1000 bars through Redis; this fills a table years deep, page by page,
and must survive Binance rate limits and restarts halfway through. The SQL
lives in repositories.history_repository; everything here is testable without
a database.
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

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


BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
PAGE_LIMIT = 1000
MAX_ATTEMPTS = 5
# Binance uses 418 once an IP has ignored 429s; both carry Retry-After.
RATE_LIMITED = (418, 429)


class HistoryFetchError(RuntimeError):
    """A page could not be fetched after retries, or the request was invalid."""


async def fetch_page(
    client: Any,
    symbol: str,
    timeframe: str,
    start_ms: int,
    *,
    now_ms: int,
    sleep=asyncio.sleep,
) -> List[Dict[str, Any]]:
    """
    One page of up to 1000 closed candles starting at start_ms.

    Rate limits wait for as long as Binance asks. Server errors and network
    failures back off exponentially. A 4xx other than a rate limit means the
    request itself is wrong, so retrying would only burn weight.
    """
    params = {
        "symbol": symbol.upper(),
        "interval": timeframe,
        "startTime": start_ms,
        "limit": PAGE_LIMIT,
    }
    last_error = "no attempt made"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await client.get(BINANCE_KLINES, params=params)
        except httpx.HTTPError as exc:
            last_error = f"network error: {exc}"
            await sleep(float(2 ** attempt))
            continue

        if response.status_code == 200:
            rows = response.json()
            if not isinstance(rows, list):
                raise HistoryFetchError(f"Unexpected kline response for {symbol} {timeframe}")
            return parse_klines(rows, now_ms)

        if response.status_code in RATE_LIMITED:
            last_error = f"rate limited ({response.status_code})"
            await sleep(float(response.headers.get("Retry-After", 60)))
            continue

        if response.status_code >= 500:
            last_error = f"server error {response.status_code}"
            await sleep(float(2 ** attempt))
            continue

        raise HistoryFetchError(
            f"Binance refused {symbol} {timeframe} ({response.status_code}): {response.text[:200]}"
        )

    raise HistoryFetchError(
        f"Gave up on {symbol} {timeframe} from {start_ms} after {MAX_ATTEMPTS} attempts: {last_error}"
    )


PAGE_PAUSE_SECONDS = 0.3


@dataclass
class BackfillResult:
    symbol: str
    timeframe: str
    pages: int
    bars: int
    error: Optional[str] = None


def _default_repo():
    # Imported lazily so the pure helpers above import without a database.
    from repositories.history_repository import HistoryRepository

    return HistoryRepository


async def backfill(
    symbol: str,
    timeframe: str,
    *,
    client: Any,
    now_ms: int,
    repo: Any = None,
    fetch=None,
    sleep=asyncio.sleep,
) -> BackfillResult:
    """
    Bring one series up to the newest closed bar, then trim past its depth.

    Resumes after the newest stored bar, so a restart repeats nothing. Each page
    is stored as soon as it arrives: a failure part-way keeps every earlier page
    and reports the error instead of raising, so one bad pair cannot stop the
    others.
    """
    repo = repo or _default_repo()
    fetch = fetch or fetch_page
    step = _step(timeframe)
    floor = depth_start_ms(timeframe, now_ms)

    latest = await repo.latest_time(symbol, timeframe)
    cursor = floor if latest is None else max(floor, latest + step)
    newest_closed = now_ms - (now_ms % step) - step

    pages = 0
    bars = 0
    error: Optional[str] = None
    while cursor <= newest_closed:
        try:
            candles = await fetch(client, symbol, timeframe, cursor, now_ms=now_ms, sleep=sleep)
        except HistoryFetchError as exc:
            error = str(exc)
            break
        pages += 1
        if not candles:
            break
        bars += await repo.upsert(symbol, timeframe, candles)
        advanced_to = candles[-1]["time"] + step
        if advanced_to <= cursor:
            break  # the exchange handed back what we already asked past
        cursor = advanced_to
        if cursor <= newest_closed:
            await sleep(PAGE_PAUSE_SECONDS)

    if HISTORY_DEPTH_DAYS[timeframe] is not None:
        await repo.trim(symbol, timeframe, floor)

    return BackfillResult(symbol.upper(), timeframe, pages, bars, error)


async def topup_all(
    *,
    client: Any,
    now_ms: Optional[int] = None,
    pairs: Tuple[str, ...] = PAIRS,
    timeframes: Tuple[str, ...] = tuple(TIMEFRAME_MS),
    run=None,
) -> List[BackfillResult]:
    """
    Every pair and timeframe, one series at a time.

    Sequential on purpose: the worker shares a small VM and an IP's Binance
    weight with the live API. The first run on an empty table is the full
    backfill (minutes); every run after that fetches about one page per series.
    """
    run = run or backfill
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    results: List[BackfillResult] = []
    for symbol in pairs:
        for timeframe in timeframes:
            try:
                results.append(await run(symbol, timeframe, client=client, now_ms=now_ms))
            except Exception as exc:  # one broken series must not stop the rest
                results.append(BackfillResult(symbol, timeframe, 0, 0, error=str(exc)))
    return results
