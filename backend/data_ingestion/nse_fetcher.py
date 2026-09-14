"""
NSE (National Stock Exchange India) Data Fetcher
Fetches live and historical stock data from Indian stock market
"""

import httpx
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio
from repositories.ohlc_repository import OHLCRepository


class NSEFetcher:
    """
    Fetches stock data from NSE India using Yahoo Finance API
    (Free alternative to paid NSE API)
    """

    def __init__(self):
        self.base_url = "https://query1.finance.yahoo.com/v8/finance/chart/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    async def fetch_ohlc(
        self,
        symbol: str,
        interval: str = "1h",
        period: str = "10d"
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLC data from Yahoo Finance for Indian stocks

        Args:
            symbol: NSE symbol (e.g., "RELIANCE.NS", "TCS.NS", "INFY.NS")
            interval: Candle interval (1m, 5m, 15m, 30m, 1h, 1d)
            period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)

        Returns:
            List of OHLC dictionaries
        """
        # Add .NS suffix for NSE stocks if not present
        if not symbol.endswith('.NS') and not symbol.endswith('.BO'):
            symbol = f"{symbol}.NS"

        url = f"{self.base_url}{symbol}"
        params = {
            'interval': interval,
            'period': period,
            'includePrePost': 'false'
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

        # Parse Yahoo Finance response
        chart_data = data['chart']['result'][0]
        timestamps = chart_data['timestamp']
        quotes = chart_data['indicators']['quote'][0]

        ohlc_data = []
        for i in range(len(timestamps)):
            # Skip if any value is None
            if (quotes['open'][i] is None or
                quotes['high'][i] is None or
                quotes['low'][i] is None or
                quotes['close'][i] is None):
                continue

            ohlc_data.append({
                'time': datetime.fromtimestamp(timestamps[i]),
                'open': float(quotes['open'][i]),
                'high': float(quotes['high'][i]),
                'low': float(quotes['low'][i]),
                'close': float(quotes['close'][i]),
                'volume': float(quotes['volume'][i] or 0)
            })

        return ohlc_data

    async def fetch_nse_top_stocks(self) -> List[str]:
        """
        Get list of popular NSE stocks (Nifty 50 components)

        Returns:
            List of stock symbols with .NS suffix
        """
        nifty50_stocks = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
            "HINDUNILVR", "BHARTIARTL", "ITC", "SBIN", "KOTAKBANK",
            "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE",
            "HCLTECH", "SUNPHARMA", "TITAN", "ULTRACEMCO", "NESTLEIND",
            "WIPRO", "ADANIPORTS", "ONGC", "NTPC", "POWERGRID",
            "TATASTEEL", "BAJAJFINSV", "M&M", "TECHM", "INDUSINDBK",
            "JSWSTEEL", "HINDALCO", "DIVISLAB", "DRREDDY", "CIPLA",
            "EICHERMOT", "BPCL", "COALINDIA", "GRASIM", "HEROMOTOCO",
            "BRITANNIA", "SHREECEM", "UPL", "APOLLOHOSP", "TATAMOTORS",
            "SBILIFE", "BAJAJ-AUTO", "HDFCLIFE", "TATACONSUM", "ADANIENT"
        ]

        return [f"{stock}.NS" for stock in nifty50_stocks]

    async def store_to_database(
        self,
        symbol: str,
        timeframe: str,
        ohlc_data: List[Dict[str, Any]]
    ):
        """
        Store fetched OHLC data to TimescaleDB

        Args:
            symbol: Stock symbol (with .NS suffix)
            timeframe: Timeframe (1h, 1d, etc.)
            ohlc_data: List of OHLC dictionaries
        """
        # Remove .NS/.BO suffix for storage (cleaner symbol names)
        clean_symbol = symbol.replace('.NS', '').replace('.BO', '')

        await OHLCRepository.insert_ohlc_data(
            symbol=clean_symbol,
            timeframe=timeframe,
            data=ohlc_data
        )

        print(f"[OK] Stored {len(ohlc_data)} candles for {clean_symbol} ({timeframe})")

    async def fetch_and_store_multiple(
        self,
        symbols: List[str],
        interval: str = "1h",
        period: str = "10d"
    ):
        """
        Fetch and store data for multiple symbols in parallel

        Args:
            symbols: List of stock symbols
            interval: Candle interval
            period: Time period
        """
        tasks = []
        for symbol in symbols:
            task = self._fetch_and_store_single(symbol, interval, period)
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
        period: str
    ):
        """Helper method to fetch and store single symbol"""
        try:
            ohlc_data = await self.fetch_ohlc(symbol, interval, period)

            if ohlc_data:
                await self.store_to_database(symbol, interval, ohlc_data)
            else:
                print(f"[WARNING] No data found for {symbol}")

        except Exception as e:
            print(f"[ERROR] Error fetching {symbol}: {str(e)}")
            raise

    async def get_live_price(self, symbol: str) -> Optional[float]:
        """
        Get current live price for a symbol

        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS")

        Returns:
            Current price or None
        """
        try:
            # Add .NS if not present
            if not symbol.endswith('.NS') and not symbol.endswith('.BO'):
                symbol = f"{symbol}.NS"

            url = f"{self.base_url}{symbol}"
            params = {
                'interval': '1m',
                'range': '1d'
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()

            # Get latest price
            quotes = data['chart']['result'][0]['indicators']['quote'][0]
            latest_close = quotes['close'][-1]

            return float(latest_close) if latest_close else None

        except Exception as e:
            print(f"Error fetching live price for {symbol}: {e}")
            return None


# Example usage for testing
async def main():
    """Test NSE data fetching"""
    fetcher = NSEFetcher()

    # Test single stock
    print("[TEST] Fetching RELIANCE data...")
    reliance_data = await fetcher.fetch_ohlc("RELIANCE.NS", interval="1h", period="10d")
    print(f"[OK] Fetched {len(reliance_data)} candles for RELIANCE")

    # Test live price
    live_price = await fetcher.get_live_price("RELIANCE")
    print(f"[PRICE] RELIANCE live price: Rs.{live_price}")


if __name__ == "__main__":
    asyncio.run(main())
