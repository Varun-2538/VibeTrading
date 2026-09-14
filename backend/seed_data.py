#!/usr/bin/env python3
"""
Seed Script - Populate database with initial NSE India stock data
Run this script to fetch and store historical data before starting the API
"""

import asyncio
import sys
from data_ingestion.nse_fetcher import NSEFetcher
from models.database import db
from config.settings import settings


async def seed_database():
    """Seed database with NSE India stock data"""

    print("=" * 60)
    print("  TradeSmart.AI - Database Seeding")
    print("  NSE India Stock Data")
    print("=" * 60)
    print()

    # Connect to database
    print("📊 Connecting to TimescaleDB...")
    try:
        await db.connect()
        print("✅ Connected to TimescaleDB")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)

    # Initialize fetcher
    fetcher = NSEFetcher()

    # Get popular stocks
    print("\n📈 Fetching Nifty 50 stock list...")
    symbols = await fetcher.fetch_nse_top_stocks()
    print(f"✅ Found {len(symbols)} stocks")

    # Ask user how many stocks to seed
    print("\nHow many stocks do you want to seed?")
    print("1. Top 10 (Quick - ~2 minutes)")
    print("2. Top 20 (Medium - ~5 minutes)")
    print("3. Top 50 (Full - ~10 minutes)")
    print("4. Custom number")

    choice = input("\nEnter choice (1-4): ").strip()

    if choice == "1":
        stock_count = 10
    elif choice == "2":
        stock_count = 20
    elif choice == "3":
        stock_count = 50
    elif choice == "4":
        try:
            stock_count = int(input("Enter number of stocks: "))
            stock_count = min(stock_count, len(symbols))
        except:
            print("Invalid input. Using default 10.")
            stock_count = 10
    else:
        print("Invalid choice. Using default 10.")
        stock_count = 10

    selected_symbols = symbols[:stock_count]

    print(f"\n🚀 Starting data ingestion for {stock_count} stocks...")
    print(f"📊 Timeframes: 1h (10 days) and 1d (30 days)")
    print()

    # Fetch hourly data (10 days)
    print("⏳ Fetching 1h data (10 days)...")
    try:
        await fetcher.fetch_and_store_multiple(
            symbols=selected_symbols,
            interval="1h",
            period="10d"
        )
        print("✅ Hourly data stored")
    except Exception as e:
        print(f"❌ Hourly data fetch failed: {e}")

    # Fetch daily data (30 days)
    print("\n⏳ Fetching 1d data (30 days)...")
    try:
        await fetcher.fetch_and_store_multiple(
            symbols=selected_symbols,
            interval="1d",
            period="30d"
        )
        print("✅ Daily data stored")
    except Exception as e:
        print(f"❌ Daily data fetch failed: {e}")

    # Disconnect
    await db.disconnect()

    print("\n" + "=" * 60)
    print("  ✅ Database Seeding Complete!")
    print("=" * 60)
    print()
    print("📊 Your database now contains:")
    print(f"   - {stock_count} NSE stocks")
    print("   - Hourly data (10 days)")
    print("   - Daily data (30 days)")
    print()
    print("🚀 You can now start the API:")
    print("   python main.py")
    print()


if __name__ == "__main__":
    asyncio.run(seed_database())
