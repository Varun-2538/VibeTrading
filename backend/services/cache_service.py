import json
import redis.asyncio as redis
from typing import Any, Optional
from datetime import timedelta
from config.settings import settings


class CacheService:
    """Service for Redis caching operations"""

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None

    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis_client = await redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        except Exception as e:
            # Redis unavailable - continue without caching
            self.redis_client = None
            print(f"[WARNING] Redis connection failed: {e} - Running without cache")

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis_client:
            await self.redis_client.close()

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if not self.redis_client:
            return None

        try:
            value = await self.redis_client.get(key)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
        except Exception:
            # Redis unavailable - gracefully return None
            return None

    async def set(
        self,
        key: str,
        value: Any,
        expiration: Optional[int] = None
    ) -> bool:
        """
        Set value in cache

        Args:
            key: Cache key
            value: Value to cache
            expiration: Expiration time in seconds (None for no expiration)

        Returns:
            True if successful
        """
        if not self.redis_client:
            return False

        try:
            # Serialize value to JSON if it's not a string
            if not isinstance(value, str):
                value = json.dumps(value)

            if expiration:
                await self.redis_client.setex(key, expiration, value)
            else:
                await self.redis_client.set(key, value)

            return True
        except Exception:
            # Redis unavailable - gracefully return False
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete key from cache

        Args:
            key: Cache key

        Returns:
            True if deleted
        """
        if not self.redis_client:
            return False

        result = await self.redis_client.delete(key)
        return result > 0

    async def exists(self, key: str) -> bool:
        """
        Check if key exists in cache

        Args:
            key: Cache key

        Returns:
            True if key exists
        """
        if not self.redis_client:
            return False

        return await self.redis_client.exists(key) > 0

    async def get_ohlc_cache_key(
        self,
        symbol: str,
        timeframe: str,
        limit: int
    ) -> str:
        """
        Generate cache key for OHLC data

        Args:
            symbol: Trading pair
            timeframe: Timeframe
            limit: Data limit

        Returns:
            Cache key string
        """
        return f"ohlc:{symbol}:{timeframe}:{limit}"

    async def get_indicator_cache_key(
        self,
        symbol: str,
        timeframe: str,
        indicators: str
    ) -> str:
        """
        Generate cache key for indicator data

        Args:
            symbol: Trading pair
            timeframe: Timeframe
            indicators: Comma-separated indicator names

        Returns:
            Cache key string
        """
        return f"indicators:{symbol}:{timeframe}:{indicators}"

    async def get_strategy_cache_key(
        self,
        prompt_hash: str,
        symbol: str
    ) -> str:
        """
        Generate cache key for strategy

        Args:
            prompt_hash: Hash of user prompt
            symbol: Trading pair

        Returns:
            Cache key string
        """
        return f"strategy:{prompt_hash}:{symbol}"

    async def cache_ohlc_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        data: Any,
        expiration: int = 3600  # 1 hour default
    ) -> bool:
        """
        Cache OHLC data

        Args:
            symbol: Trading pair
            timeframe: Timeframe
            limit: Data limit
            data: OHLC data to cache
            expiration: Cache expiration in seconds

        Returns:
            True if successful
        """
        key = await self.get_ohlc_cache_key(symbol, timeframe, limit)
        return await self.set(key, data, expiration)

    async def get_cached_ohlc_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int
    ) -> Optional[Any]:
        """
        Get cached OHLC data

        Args:
            symbol: Trading pair
            timeframe: Timeframe
            limit: Data limit

        Returns:
            Cached OHLC data or None
        """
        key = await self.get_ohlc_cache_key(symbol, timeframe, limit)
        return await self.get(key)

    async def invalidate_ohlc_cache(self, symbol: str) -> bool:
        """
        Invalidate all OHLC cache for a symbol

        Args:
            symbol: Trading pair

        Returns:
            True if successful
        """
        if not self.redis_client:
            return False

        # Find all keys matching pattern
        pattern = f"ohlc:{symbol}:*"
        keys = await self.redis_client.keys(pattern)

        if keys:
            await self.redis_client.delete(*keys)

        return True

    async def cache_strategy(
        self,
        prompt_hash: str,
        symbol: str,
        strategy_data: Any,
        expiration: int = 7200  # 2 hours default
    ) -> bool:
        """
        Cache a generated strategy

        Args:
            prompt_hash: Hash of user prompt
            symbol: Trading pair
            strategy_data: Strategy data to cache
            expiration: Cache expiration in seconds

        Returns:
            True if successful
        """
        key = await self.get_strategy_cache_key(prompt_hash, symbol)
        return await self.set(key, strategy_data, expiration)

    async def get_cached_strategy(
        self,
        prompt_hash: str,
        symbol: str
    ) -> Optional[Any]:
        """
        Get cached strategy

        Args:
            prompt_hash: Hash of user prompt
            symbol: Trading pair

        Returns:
            Cached strategy or None
        """
        key = await self.get_strategy_cache_key(prompt_hash, symbol)
        return await self.get(key)

    async def set_with_ttl(
        self,
        key: str,
        value: Any,
        ttl_seconds: int
    ) -> bool:
        """
        Set value with time-to-live

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: TTL in seconds

        Returns:
            True if successful
        """
        return await self.set(key, value, ttl_seconds)

    async def increment(self, key: str) -> int:
        """
        Increment a counter

        Args:
            key: Cache key

        Returns:
            New counter value
        """
        if not self.redis_client:
            return 0

        return await self.redis_client.incr(key)

    async def decrement(self, key: str) -> int:
        """
        Decrement a counter

        Args:
            key: Cache key

        Returns:
            New counter value
        """
        if not self.redis_client:
            return 0

        return await self.redis_client.decr(key)

    async def get_liquidity_cache_key(
        self,
        symbol: str,
        timeframe: str
    ) -> str:
        """
        Generate cache key for liquidity levels

        Args:
            symbol: Trading pair
            timeframe: Timeframe

        Returns:
            Cache key string
        """
        return f"liquidity:{symbol}:{timeframe}"

    async def cache_liquidity_levels(
        self,
        symbol: str,
        timeframe: str,
        levels: Any,
        expiration: int = 300  # 5 minutes default for live data
    ) -> bool:
        """
        Cache liquidity levels with short TTL for live trading

        Args:
            symbol: Trading pair
            timeframe: Timeframe
            levels: Liquidity level data to cache
            expiration: Cache expiration in seconds (default 5 min)

        Returns:
            True if successful
        """
        key = await self.get_liquidity_cache_key(symbol, timeframe)
        return await self.set(key, levels, expiration)

    async def get_cached_liquidity_levels(
        self,
        symbol: str,
        timeframe: str
    ) -> Optional[Any]:
        """
        Get cached liquidity levels

        Args:
            symbol: Trading pair
            timeframe: Timeframe

        Returns:
            Cached liquidity levels or None
        """
        key = await self.get_liquidity_cache_key(symbol, timeframe)
        return await self.get(key)

    async def invalidate_liquidity_cache(self, symbol: str) -> bool:
        """
        Invalidate all liquidity cache for a symbol

        Args:
            symbol: Trading pair

        Returns:
            True if successful
        """
        if not self.redis_client:
            return False

        # Find all keys matching pattern
        pattern = f"liquidity:{symbol}:*"
        keys = await self.redis_client.keys(pattern)

        if keys:
            await self.redis_client.delete(*keys)

        return True


# Global cache service instance
cache_service = CacheService()
