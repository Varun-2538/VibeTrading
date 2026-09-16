"""
SQL for candles_history.

Times cross this boundary as unix milliseconds and are stored as timestamptz in
UTC. Nothing outside this file sees a datetime for a candle.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models.database import db


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def dt_to_ms(dt: datetime) -> int:
    return int(round(dt.timestamp() * 1000))


def to_row(symbol: str, timeframe: str, candle: Dict[str, Any]) -> Tuple:
    return (
        symbol.upper(),
        timeframe,
        ms_to_dt(int(candle["time"])),
        float(candle["open"]),
        float(candle["high"]),
        float(candle["low"]),
        float(candle["close"]),
        float(candle["volume"]),
    )


def from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "time": dt_to_ms(record["time"]),
        "open": float(record["open"]),
        "high": float(record["high"]),
        "low": float(record["low"]),
        "close": float(record["close"]),
        "volume": float(record["volume"]),
    }


class HistoryRepository:
    @staticmethod
    async def upsert(symbol: str, timeframe: str, candles: List[Dict[str, Any]]) -> int:
        if not candles:
            return 0
        query = """
            INSERT INTO candles_history (symbol, timeframe, time, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (symbol, timeframe, time) DO UPDATE
            SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, volume = EXCLUDED.volume
        """
        async with db.pool.acquire() as conn:
            await conn.executemany(query, [to_row(symbol, timeframe, c) for c in candles])
        return len(candles)

    @staticmethod
    async def latest_time(symbol: str, timeframe: str) -> Optional[int]:
        row = await db.fetchrow(
            "SELECT max(time) AS t FROM candles_history WHERE symbol = $1 AND timeframe = $2",
            symbol.upper(),
            timeframe,
        )
        return dt_to_ms(row["t"]) if row and row["t"] is not None else None

    @staticmethod
    async def load(
        symbol: str,
        timeframe: str,
        start_ms: int = 0,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        args: List[Any] = [symbol.upper(), timeframe, ms_to_dt(start_ms)]
        clause = ""
        if end_ms is not None:
            args.append(ms_to_dt(end_ms))
            clause = "AND time <= $4"
        rows = await db.fetch(
            f"""
            SELECT time, open, high, low, close, volume FROM candles_history
            WHERE symbol = $1 AND timeframe = $2 AND time >= $3 {clause}
            ORDER BY time ASC
            """,
            *args,
        )
        return [from_record(r) for r in rows]

    @staticmethod
    async def trim(symbol: str, timeframe: str, before_ms: int) -> None:
        await db.execute(
            "DELETE FROM candles_history WHERE symbol = $1 AND timeframe = $2 AND time < $3",
            symbol.upper(),
            timeframe,
            ms_to_dt(before_ms),
        )

    @staticmethod
    async def coverage() -> List[Dict[str, Any]]:
        rows = await db.fetch(
            """
            SELECT symbol, timeframe, min(time) AS first, max(time) AS last, count(*) AS bars
            FROM candles_history
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
            """
        )
        return [
            {
                "symbol": r["symbol"],
                "timeframe": r["timeframe"],
                "first": dt_to_ms(r["first"]),
                "last": dt_to_ms(r["last"]),
                "bars": int(r["bars"]),
            }
            for r in rows
        ]
