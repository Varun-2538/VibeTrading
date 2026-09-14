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
    async def get_price_levels(
        symbol: str,
        timeframe: str = "1h",
        lookback_periods: int = 240
    ) -> Dict[str, List[float]]:
        """
        Extract significant price levels (highs and lows) for liquidation analysis

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            lookback_periods: Number of periods to analyze

        Returns:
            Dictionary with 'highs' and 'lows' lists
        """
        query = """
            SELECT
                high,
                low,
                close
            FROM ohlc_data
            WHERE symbol = $1 AND timeframe = $2
            ORDER BY time DESC
            LIMIT $3
        """

        data = await db.fetch(query, symbol, timeframe, lookback_periods)

        highs = [row['high'] for row in data]
        lows = [row['low'] for row in data]

        return {
            'highs': highs,
            'lows': lows,
            'closes': [row['close'] for row in data]
        }

    @staticmethod
    async def calculate_support_resistance(
        symbol: str,
        timeframe: str = "1h",
        lookback_periods: int = 240,
        sensitivity: float = 0.02  # 2% price tolerance
    ) -> Dict[str, List[float]]:
        """
        Calculate support and resistance levels based on historical price action

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            lookback_periods: Periods to analyze
            sensitivity: Price clustering tolerance (as decimal)

        Returns:
            Dictionary with 'support' and 'resistance' levels
        """
        price_data = await OHLCRepository.get_price_levels(
            symbol, timeframe, lookback_periods
        )

        highs = price_data['highs']
        lows = price_data['lows']

        # Find resistance levels (clustered highs)
        resistance_levels = await OHLCRepository._find_price_clusters(
            highs, sensitivity
        )

        # Find support levels (clustered lows)
        support_levels = await OHLCRepository._find_price_clusters(
            lows, sensitivity
        )

        return {
            'support': sorted(support_levels)[:5],  # Top 5 support levels
            'resistance': sorted(resistance_levels, reverse=True)[:5]  # Top 5 resistance
        }

    @staticmethod
    async def _find_price_clusters(
        prices: List[float],
        sensitivity: float
    ) -> List[float]:
        """
        Find price clusters (areas where price frequently tested)

        Args:
            prices: List of prices
            sensitivity: Clustering tolerance

        Returns:
            List of clustered price levels
        """
        if not prices:
            return []

        clusters = {}

        for price in prices:
            # Find if price belongs to existing cluster
            found_cluster = False
            for cluster_key in list(clusters.keys()):
                if abs(price - cluster_key) / cluster_key <= sensitivity:
                    clusters[cluster_key].append(price)
                    found_cluster = True
                    break

            if not found_cluster:
                clusters[price] = [price]

        # Calculate average price for each cluster and weight by frequency
        weighted_levels = []
        for prices_in_cluster in clusters.values():
            if len(prices_in_cluster) >= 2:  # Only significant clusters
                avg_price = sum(prices_in_cluster) / len(prices_in_cluster)
                weighted_levels.append(avg_price)

        return weighted_levels

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
