"""
CandleService - the single supplier of candles.

Both the chart and every analysis path read candles through here, so the
candles a detector runs over are by construction the candles the trader is
looking at. Two sources would mean levels and patterns marked at prices that
do not match the chart, which is a correctness bug in every feature built on
top, so it is designed out rather than managed.

This talks to Binance directly rather than through BinanceFetcher: that class
swallows request failures into an empty list (indistinguishable from "no data")
and builds timezone-naive local datetimes. Here times stay unix milliseconds
and failures propagate, so the API can answer 502 instead of an empty chart.
"""
from typing import Any, Dict, List, Optional
import asyncio
import httpx

from services.cache_service import cache_service


BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

# Cache TTL per timeframe, in seconds - roughly a third of the candle period,
# so a cached response is never stale by more than a fraction of one candle.
TIMEFRAME_TTL: Dict[str, int] = {
    "1m": 20,
    "5m": 60,
    "15m": 180,
    "1h": 300,
    "1d": 900,
}

MAX_LIMIT = 1000


# One shared client for the process. Building an httpx client per request
# means a fresh SSL context and a fresh TLS handshake every time, which cost
# roughly eight seconds per call on Windows - long enough that the chart
# looked broken. Reusing the client keeps the connection pool warm.
_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        async with _client_lock:
            if _client is None or _client.is_closed:
                _client = httpx.AsyncClient(
                    timeout=httpx.Timeout(15.0, connect=10.0),
                    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                )
    return _client


async def close_http() -> None:
    """Close the shared client. Called from the app's shutdown hook."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class UnknownTimeframe(ValueError):
    """Raised for a timeframe we do not serve."""


class CandleFetchError(RuntimeError):
    """Raised when candles could not be retrieved from upstream."""


class CandleService:
    @staticmethod
    def timeframes() -> List[str]:
        return list(TIMEFRAME_TTL)

    @staticmethod
    async def get_candles(
        symbol: str,
        timeframe: str = "1h",
        limit: int = MAX_LIMIT,
    ) -> List[Dict[str, Any]]:
        """
        Candles in chronological order, oldest first.

        Each candle is {time, open, high, low, close, volume} where time is the
        candle's open time in unix milliseconds.
        """
        if timeframe not in TIMEFRAME_TTL:
            raise UnknownTimeframe(
                f"Unknown timeframe '{timeframe}'. Expected one of: "
                f"{', '.join(TIMEFRAME_TTL)}"
            )

        symbol = symbol.upper()
        limit = max(1, min(int(limit), MAX_LIMIT))
        key = f"candles:{symbol}:{timeframe}:{limit}"

        cached = await cache_service.get(key)
        if cached:
            return cached

        candles = await CandleService._fetch(symbol, timeframe, limit)

        # A cache write failure is not worth failing the request over - the
        # cache is an optimisation, never a source of truth.
        await cache_service.set(key, candles, TIMEFRAME_TTL[timeframe])
        return candles

    @staticmethod
    async def _fetch(symbol: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        try:
            client = await _http()
            response = await client.get(
                BINANCE_KLINES,
                params={"symbol": symbol, "interval": timeframe, "limit": limit},
            )
            response.raise_for_status()
            rows = response.json()
        except httpx.HTTPError as exc:
            raise CandleFetchError(
                f"Could not reach Binance for {symbol} {timeframe}: {exc}"
            ) from exc

        if not isinstance(rows, list):
            raise CandleFetchError(f"Unexpected response shape for {symbol} {timeframe}")

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
        ]

    @staticmethod
    def window(
        candles: List[Dict[str, Any]],
        frm: Optional[int] = None,
        to: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        The candles inside a visible range, bounds inclusive, in unix ms.

        Either bound may be omitted to leave that side open. Zooming past the
        available data yields an empty list rather than an error - the caller
        clears its overlay.
        """
        return [
            c
            for c in candles
            if (frm is None or c["time"] >= frm) and (to is None or c["time"] <= to)
        ]


candle_service = CandleService()
