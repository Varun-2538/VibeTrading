"""
Crypto Data Scheduler - Automatically fetches live crypto data from Binance
Crypto markets are 24/7, so we fetch more frequently than stock markets
"""

import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from data_ingestion.binance_fetcher import BinanceFetcher
from repositories.ohlc_repository import OHLCRepository


class CryptoScheduler:
    """
    Schedules periodic crypto data fetching and cleanup tasks
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.binance_fetcher = BinanceFetcher()
        self.is_running = False

        # Crypto pairs to track
        self.crypto_pairs = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT"
        ]

    async def start(self):
        """Start the crypto scheduler"""
        if self.is_running:
            print("[WARNING] Crypto scheduler already running")
            return

        # Fetch live data every 5 minutes (crypto is 24/7)
        self.scheduler.add_job(
            self.fetch_live_data,
            trigger=IntervalTrigger(minutes=5),
            id='live_crypto_update',
            name='Fetch live crypto data every 5 minutes',
            replace_existing=True
        )

        # Cleanup old data daily at 00:00 UTC (keep last 30 days)
        self.scheduler.add_job(
            self.cleanup_old_data,
            trigger=CronTrigger(hour=0, minute=0),
            id='daily_cleanup',
            name='Cleanup data older than 30 days',
            replace_existing=True
        )

        # Initial data fetch on startup
        self.scheduler.add_job(
            self.initial_data_fetch,
            trigger='date',  # Run once
            id='initial_crypto_fetch',
            name='Initial crypto data fetch'
        )

        self.scheduler.start()
        self.is_running = True
        print("[OK] Crypto scheduler started")
        print("   - Live updates: Every 5 minutes (24/7)")
        print("   - Data retention: Last 30 days")
        print("   - Daily cleanup: 00:00 UTC")

    async def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.is_running = False
            print("[OK] Crypto scheduler stopped")

    async def initial_data_fetch(self):
        """Fetch initial historical data on startup"""
        print("\n[STARTUP] Fetching initial crypto data from Binance...")

        try:
            success_count = 0
            fail_count = 0

            for symbol in self.crypto_pairs:
                try:
                    # Fetch last 500 hourly candles (~21 days)
                    candles = await self.binance_fetcher.fetch_ohlc(
                        symbol=symbol,
                        interval="1h",
                        limit=500
                    )

                    # Store in database using bulk insert
                    if candles:
                        await OHLCRepository.insert_ohlc_data(
                            symbol=symbol,
                            timeframe="1h",
                            data=candles
                        )
                        print(f"[OK] Stored {len(candles)} candles for {symbol}")
                        success_count += 1

                except Exception as e:
                    print(f"[ERROR] Failed to fetch {symbol}: {e}")
                    fail_count += 1

            print(f"\n[INGESTION] Complete:")
            print(f"   [OK] Success: {success_count}/{len(self.crypto_pairs)}")
            print(f"   [ERROR] Failed: {fail_count}/{len(self.crypto_pairs)}")

        except Exception as e:
            print(f"[ERROR] Initial crypto fetch failed: {e}")

    async def fetch_live_data(self):
        """Fetch latest crypto data (runs every 5 minutes)"""
        print(f"\n[LIVE UPDATE] {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

        try:
            success_count = 0
            fail_count = 0

            for symbol in self.crypto_pairs:
                try:
                    # Fetch last 10 candles to ensure we have latest
                    candles = await self.binance_fetcher.fetch_ohlc(
                        symbol=symbol,
                        interval="1h",
                        limit=10
                    )

                    # Store all recent candles (upsert will handle duplicates)
                    if candles:
                        await OHLCRepository.insert_ohlc_data(
                            symbol=symbol,
                            timeframe="1h",
                            data=candles
                        )
                        success_count += 1

                except Exception as e:
                    print(f"[ERROR] Live update failed for {symbol}: {e}")
                    fail_count += 1

            print(f"[LIVE] Updated {success_count} cryptos (Failed: {fail_count})")

        except Exception as e:
            print(f"[ERROR] Live update failed: {e}")

    async def cleanup_old_data(self):
        """Remove data older than 30 days"""
        print(f"\n[CLEANUP] Starting data cleanup at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

        try:
            cutoff_date = datetime.utcnow() - timedelta(days=30)

            for symbol in self.crypto_pairs:
                try:
                    deleted_count = await OHLCRepository.delete_old_data(
                        symbol=symbol,
                        before_date=cutoff_date
                    )

                    if deleted_count > 0:
                        print(f"[CLEANUP] Deleted {deleted_count} old candles for {symbol}")

                except Exception as e:
                    print(f"[ERROR] Cleanup failed for {symbol}: {e}")

            print("[CLEANUP] Data cleanup complete")

        except Exception as e:
            print(f"[ERROR] Cleanup failed: {e}")


# Global instance
crypto_scheduler = CryptoScheduler()
