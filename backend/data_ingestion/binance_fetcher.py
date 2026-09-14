"""
Binance Crypto Data Fetcher
Fetches OHLC data from Binance public API (no API key needed)
"""
import httpx
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from repositories.ohlc_repository import OHLCRepository


class BinanceFetcher:
    """Fetch cryptocurrency data from Binance"""

    BASE_URL = "https://api.binance.com/api/v3"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def fetch_ohlc(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLC data from Binance

        Args:
            symbol: Trading pair (e.g., BTCUSDT, ETHUSDT)
            interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d)
            limit: Number of candles (max 1000)

        Returns:
            List of OHLC dictionaries
        """
        try:
            # Map our intervals to Binance format
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d"
            }

            binance_interval = interval_map.get(interval, "1h")

            # Fetch klines (candlestick data)
            url = f"{self.BASE_URL}/klines"
            params = {
                "symbol": symbol,
                "interval": binance_interval,
                "limit": min(limit, 1000)
            }

            response = await self.client.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            # Parse Binance klines format
            # [Open time, Open, High, Low, Close, Volume, Close time, ...]
            ohlc_data = []
            for candle in data:
                ohlc_data.append({
                    "time": datetime.fromtimestamp(candle[0] / 1000),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5])
                })

            return ohlc_data

        except httpx.HTTPError as e:
            print(f"[ERROR] Binance API error for {symbol}: {e}")
            return []
        except Exception as e:
            print(f"[ERROR] Error fetching {symbol}: {e}")
            return []

    async def store_to_database(
        self,
        symbol: str,
        timeframe: str,
        ohlc_data: List[Dict[str, Any]]
    ):
        """Store OHLC data to database"""
        if not ohlc_data:
            return

        await OHLCRepository.insert_ohlc_data(
            symbol=symbol,
            timeframe=timeframe,
            data=ohlc_data
        )

        print(f"[OK] Stored {len(ohlc_data)} candles for {symbol} ({timeframe})")

    async def fetch_and_store_multiple(
        self,
        symbols: List[str],
        interval: str = "1h",
        limit: int = 100
    ):
        """
        Fetch and store data for multiple symbols in parallel

        Args:
            symbols: List of trading pairs
            interval: Candle interval
            limit: Number of candles
        """
        tasks = []
        for symbol in symbols:
            task = self._fetch_and_store_single(symbol, interval, limit)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes and failures
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        failure_count = len(results) - success_count

        print(f"\n[INGESTION] Complete:")
        print(f"   [OK] Success: {success_count}/{len(symbols)}")
        print(f"   [ERROR] Failed: {failure_count}/{len(symbols)}")

    async def _fetch_and_store_single(
        self,
        symbol: str,
        interval: str,
        limit: int
    ):
        """Helper method to fetch and store single symbol"""
        try:
            ohlc_data = await self.fetch_ohlc(symbol, interval, limit)

            if ohlc_data:
                await self.store_to_database(symbol, interval, ohlc_data)
            else:
                print(f"[WARNING] No data found for {symbol}")

        except Exception as e:
            print(f"[ERROR] Error fetching {symbol}: {str(e)}")
            raise

    async def get_live_price(self, symbol: str) -> Optional[float]:
        """
        Get current live price

        Args:
            symbol: Trading pair (e.g., BTCUSDT)

        Returns:
            Current price or None
        """
        try:
            url = f"{self.BASE_URL}/ticker/price"
            params = {"symbol": symbol}

            response = await self.client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            return float(data["price"])

        except Exception as e:
            print(f"[ERROR] Error fetching live price for {symbol}: {e}")
            return None

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


# Test function
async def main():
    """Test Binance data fetching"""
    fetcher = BinanceFetcher()

    # Test single crypto
    print("[TEST] Fetching BTCUSDT data...")
    btc_data = await fetcher.fetch_ohlc("BTCUSDT", interval="1h", limit=10)
    print(f"[OK] Fetched {len(btc_data)} candles for Bitcoin")
    print(f"Latest: ${btc_data[0]['close']:,.2f}")

    # Test live price
    live_price = await fetcher.get_live_price("BTCUSDT")
    print(f"[PRICE] Bitcoin live price: ${live_price:,.2f}")

    await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())
