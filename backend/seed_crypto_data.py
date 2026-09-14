"""
Seed database with cryptocurrency data from Binance
"""
import asyncio
import sys
sys.path.insert(0, '.')

from data_ingestion.binance_fetcher import BinanceFetcher
from models.database import db


CRYPTO_PAIRS = [
    "BTCUSDT",   # Bitcoin
    "ETHUSDT",   # Ethereum
    "BNBUSDT",   # Binance Coin
    "SOLUSDT",   # Solana
    "XRPUSDT",   # Ripple
    "ADAUSDT",   # Cardano
    "DOGEUSDT",  # Dogecoin
    "MATICUSDT", # Polygon
    "DOTUSDT",   # Polkadot
    "AVAXUSDT",  # Avalanche
]


async def main():
    """Seed crypto data"""
    print("\n" + "="*80)
    print("SEEDING CRYPTOCURRENCY DATA FROM BINANCE")
    print("="*80 + "\n")

    await db.connect()
    fetcher = BinanceFetcher()

    print(f"[INFO] Fetching data for {len(CRYPTO_PAIRS)} cryptocurrencies...\n")

    for symbol in CRYPTO_PAIRS:
        try:
            print(f"[FETCHING] {symbol}...")

            # Fetch 1-hour candles (last 100)
            ohlc_data = await fetcher.fetch_ohlc(symbol, interval="1h", limit=100)

            if ohlc_data:
                # Store to database
                await fetcher.store_to_database(symbol, "1h", ohlc_data)

                # Get current price
                current_price = ohlc_data[0]['close']
                print(f"[OK] {symbol}: ${current_price:,.2f} ({len(ohlc_data)} candles)\n")
            else:
                print(f"[WARNING] No data for {symbol}\n")

        except Exception as e:
            print(f"[ERROR] Failed to fetch {symbol}: {e}\n")

    print("="*80)
    print("SEEDING COMPLETE!")
    print("="*80)

    # Summary
    print("\n[SUMMARY] Database now contains:")
    query = "SELECT symbol, COUNT(*) as count FROM ohlc_data WHERE symbol IN ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) GROUP BY symbol ORDER BY symbol"
    result = await db.pool.fetch(query, *CRYPTO_PAIRS)

    total_candles = 0
    for row in result:
        count = row['count']
        total_candles += count
        print(f"  - {row['symbol']}: {count} candles")

    print(f"\n[OK] Total: {total_candles} candles across {len(result)} cryptocurrencies")

    await fetcher.close()
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
