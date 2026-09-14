"""
Data Scheduler - Automatically fetches and updates stock data
Runs as a background task in FastAPI
"""

import asyncio
from datetime import datetime, time as dt_time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from data_ingestion.nse_fetcher import NSEFetcher


class DataScheduler:
    """
    Schedules periodic data fetching tasks
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.nse_fetcher = NSEFetcher()
        self.is_running = False

    async def start(self):
        """Start the scheduler"""
        if self.is_running:
            print("[WARNING] Scheduler already running")
            return

        # Schedule hourly updates during market hours (9:15 AM - 3:30 PM IST)
        self.scheduler.add_job(
            self.fetch_hourly_data,
            trigger=CronTrigger(
                day_of_week='mon-fri',  # Only on trading days
                hour='9-15',            # Market hours (IST)
                minute='0'              # Every hour
            ),
            id='hourly_update',
            name='Fetch hourly OHLC data',
            replace_existing=True
        )

        # Schedule daily data update at market close (3:45 PM IST)
        self.scheduler.add_job(
            self.fetch_daily_data,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=15,
                minute=45
            ),
            id='daily_update',
            name='Fetch daily OHLC data',
            replace_existing=True
        )

        # Initial data fetch on startup
        self.scheduler.add_job(
            self.initial_data_fetch,
            trigger='date',  # Run once
            id='initial_fetch',
            name='Initial data fetch on startup'
        )

        self.scheduler.start()
        self.is_running = True
        print("[OK] Data scheduler started")
        print("   - Hourly updates: Mon-Fri 9:00-15:00 IST")
        print("   - Daily updates: Mon-Fri 15:45 IST")

    async def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.is_running = False
            print("[OK] Data scheduler stopped")

    async def initial_data_fetch(self):
        """Fetch initial data on startup"""
        print("\n[STARTUP] Starting initial data fetch...")

        try:
            # Get Nifty 50 stocks
            symbols = await self.nse_fetcher.fetch_nse_top_stocks()

            # Fetch last 10 days of hourly data for top 10 stocks
            top_stocks = symbols[:10]  # Start with top 10

            print(f"[INFO] Fetching data for {len(top_stocks)} stocks...")
            await self.nse_fetcher.fetch_and_store_multiple(
                symbols=top_stocks,
                interval="1h",
                period="10d"
            )

            print("[OK] Initial data fetch complete!")

        except Exception as e:
            print(f"[ERROR] Initial data fetch failed: {e}")

    async def fetch_hourly_data(self):
        """Fetch hourly data during market hours"""
        print(f"\n[CRON] [{datetime.now()}] Fetching hourly updates...")

        try:
            # Get current trading stocks (Nifty 50)
            symbols = await self.nse_fetcher.fetch_nse_top_stocks()

            # Fetch latest hour for all stocks
            await self.nse_fetcher.fetch_and_store_multiple(
                symbols=symbols[:10],  # Top 10 for now
                interval="1h",
                period="1d"  # Just today's data
            )

            print("[OK] Hourly update complete")

        except Exception as e:
            print(f"[ERROR] Hourly update failed: {e}")

    async def fetch_daily_data(self):
        """Fetch daily data at market close"""
        print(f"\n[CRON] [{datetime.now()}] Fetching daily data...")

        try:
            symbols = await self.nse_fetcher.fetch_nse_top_stocks()

            # Fetch daily candles
            await self.nse_fetcher.fetch_and_store_multiple(
                symbols=symbols[:20],  # Top 20 stocks
                interval="1d",
                period="30d"  # Last month
            )

            print("[OK] Daily update complete")

        except Exception as e:
            print(f"[ERROR] Daily update failed: {e}")

    async def fetch_on_demand(
        self,
        symbol: str,
        interval: str = "1h",
        period: str = "10d"
    ):
        """
        Fetch data on-demand (e.g., when user requests a new symbol)

        Args:
            symbol: Stock symbol
            interval: Candle interval
            period: Time period
        """
        print(f"[ON-DEMAND] Fetch: {symbol} ({interval})")

        try:
            ohlc_data = await self.nse_fetcher.fetch_ohlc(
                symbol=symbol,
                interval=interval,
                period=period
            )

            if ohlc_data:
                await self.nse_fetcher.store_to_database(
                    symbol=symbol,
                    timeframe=interval,
                    ohlc_data=ohlc_data
                )
                print(f"[OK] Fetched {len(ohlc_data)} candles for {symbol}")
                return True
            else:
                print(f"[WARNING] No data found for {symbol}")
                return False

        except Exception as e:
            print(f"[ERROR] On-demand fetch failed for {symbol}: {e}")
            return False


# Global scheduler instance
data_scheduler = DataScheduler()
