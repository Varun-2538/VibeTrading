from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncpg
from models.database import db


class OHLCRepository:
    """Repository for OHLC data operations"""

    @staticmethod
    async def get_ohlc_data(
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLC data from TimescaleDB

        Args:
            symbol: Trading pair (e.g., BTC/USD)
            timeframe: Candle timeframe
            limit: Number of candles to fetch

        Returns:
            List of OHLC data in chronological order
        """
        query = """
            SELECT
                time,
                open,
                high,
                low,
                close,
                volume
            FROM ohlc_data
            WHERE symbol = $1 AND timeframe = $2
            ORDER BY time DESC
            LIMIT $3
        """
        data = await db.fetch(query, symbol, timeframe, limit)
        # Reverse to get chronological order (oldest to newest)
        return list(reversed(data))

    @staticmethod
    async def get_latest_candle(
        symbol: str,
        timeframe: str = "1h"
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent candle

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe

        Returns:
            Latest OHLC candle or None
        """
        query = """
            SELECT
                time,
                open,
                high,
                low,
                close,
                volume
            FROM ohlc_data
            WHERE symbol = $1 AND timeframe = $2
            ORDER BY time DESC
            LIMIT 1
        """
        return await db.fetchrow(query, symbol, timeframe)

    @staticmethod
    async def insert_ohlc_data(
        symbol: str,
        timeframe: str,
        data: List[Dict[str, Any]]
    ) -> None:
        """
        Insert or update OHLC data in bulk

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            data: List of OHLC candles with keys: time, open, high, low, close, volume
        """
        query = """
            INSERT INTO ohlc_data (time, symbol, timeframe, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (time, symbol, timeframe) DO UPDATE
            SET open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume
        """

        async with db.pool.acquire() as conn:
            await conn.executemany(query, [
                (
                    row['time'],
                    symbol,
                    timeframe,
                    float(row['open']),
                    float(row['high']),
                    float(row['low']),
                    float(row['close']),
                    float(row['volume'])
                )
                for row in data
            ])

    @staticmethod
    async def get_ohlc_range(
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """
        Get OHLC data within a time range

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            start_time: Start datetime
            end_time: End datetime

        Returns:
            List of OHLC candles in chronological order
        """
        query = """
            SELECT
                time,
                open,
                high,
                low,
                close,
                volume
            FROM ohlc_data
            WHERE symbol = $1
                AND timeframe = $2
                AND time >= $3
                AND time <= $4
            ORDER BY time ASC
        """
        return await db.fetch(query, symbol, timeframe, start_time, end_time)

    @staticmethod
    async def delete_old_data(
        symbol: str,
        before_date: datetime
    ) -> int:
        """
        Delete OHLC data older than specified date

        Args:
            symbol: Trading pair
            before_date: Delete data before this date

        Returns:
            Number of rows deleted
        """
        query = """
            DELETE FROM ohlc_data
            WHERE symbol = $1 AND time < $2
        """
        result = await db.execute(query, symbol, before_date)
        # Extract row count from result (format: "DELETE <count>")
        return int(result.split()[-1]) if result else 0
