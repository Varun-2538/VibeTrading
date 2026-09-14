"""
Simple test to detect liquidation levels using MarketDataService directly
(Without MCP - direct service layer calls)
"""
import asyncio
from models.database import db
from services.market_data_service import MarketDataService
from repositories.ohlc_repository import OHLCRepository
import json


async def analyze_stock(symbol: str):
    """Analyze liquidation levels for a stock"""
    print(f"\n{'='*80}")
    print(f"[ANALYZING] {symbol} - Support & Resistance Levels")
    print(f"{'='*80}\n")

    # Get OHLC data
    ohlc_data = await OHLCRepository.get_ohlc_data(
        symbol=symbol,
        timeframe="1h",
        limit=100
    )

    if not ohlc_data or len(ohlc_data) == 0:
        print(f"[ERROR] No data found for {symbol}")
        return None

    print(f"[DATA] Found {len(ohlc_data)} candles")

    # Current price (most recent close)
    current_price = ohlc_data[0]['close']
    print(f"[PRICE] Current: Rs.{current_price:.2f}")

    # Get price range
    prices = [c['close'] for c in ohlc_data]
    high_price = max(prices)
    low_price = min(prices)
    print(f"[RANGE] High: Rs.{high_price:.2f}, Low: Rs.{low_price:.2f}")

    # Detect liquidation levels
    print(f"\n[DETECTING] Liquidation levels...")
    levels = await MarketDataService.detect_liquidation_levels(
        symbol=symbol,
        timeframe="1h",
        lookback_periods=len(ohlc_data)
    )

    # Display Support Levels
    support_levels = levels.get('support_levels', [])
    print(f"\n[SUPPORT LEVELS] {len(support_levels)} found:")
    for i, level in enumerate(support_levels[:5], 1):
        distance_pct = ((current_price - level['price']) / current_price) * 100
        tests = level.get('test_count', 0)
        print(f"  {i}. Rs.{level['price']:.2f}")
        print(f"     Strength: {level['strength'].upper()}")
        print(f"     Distance: {distance_pct:+.2f}% from current")
        print(f"     Tests: {tests} times")

    # Display Resistance Levels
    resistance_levels = levels.get('resistance_levels', [])
    print(f"\n[RESISTANCE LEVELS] {len(resistance_levels)} found:")
    for i, level in enumerate(resistance_levels[:5], 1):
        distance_pct = ((level['price'] - current_price) / current_price) * 100
        tests = level.get('test_count', 0)
        print(f"  {i}. Rs.{level['price']:.2f}")
        print(f"     Strength: {level['strength'].upper()}")
        print(f"     Distance: {distance_pct:+.2f}% from current")
        print(f"     Tests: {tests} times")

    # Display Liquidation Zones
    liquidation_zones = levels.get('liquidation_zones', [])
    print(f"\n[LIQUIDATION ZONES] {len(liquidation_zones)} found:")
    for i, zone in enumerate(liquidation_zones[:3], 1):
        mid_price = (zone['start_price'] + zone['end_price']) / 2
        distance_pct = ((mid_price - current_price) / current_price) * 100
        zone_width = zone['end_price'] - zone['start_price']
        print(f"  {i}. Rs.{zone['start_price']:.2f} - Rs.{zone['end_price']:.2f}")
        print(f"     Type: {zone['type'].upper()}")
        print(f"     Strength: {zone['strength'].upper()}")
        print(f"     Zone Width: Rs.{zone_width:.2f}")
        print(f"     Distance: {distance_pct:+.2f}% from current")

    return {
        'symbol': symbol,
        'current_price': current_price,
        'high': high_price,
        'low': low_price,
        'candle_count': len(ohlc_data),
        'support_levels': support_levels,
        'resistance_levels': resistance_levels,
        'liquidation_zones': liquidation_zones
    }


async def main():
    """Analyze all stocks in database"""
    await db.connect()

    print("\n" + "="*80)
    print("LIQUIDATION LEVEL DETECTION - NSE INDIA STOCKS")
    print("Support & Resistance Analysis using Price Clustering")
    print("="*80)

    # Get all symbols
    query = 'SELECT DISTINCT symbol FROM ohlc_data ORDER BY symbol'
    result = await db.pool.fetch(query)
    symbols = [row['symbol'] for row in result]

    print(f"\n[INFO] Analyzing {len(symbols)} stocks...\n")

    all_results = {}

    for symbol in symbols:
        try:
            analysis = await analyze_stock(symbol)
            if analysis:
                all_results[symbol] = analysis
        except Exception as e:
            print(f"\n[ERROR] Failed to analyze {symbol}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "="*80)
    print("SUMMARY - LIQUIDATION LEVELS DETECTED")
    print("="*80 + "\n")

    summary_data = []
    for symbol, data in all_results.items():
        support_count = len(data['support_levels'])
        resistance_count = len(data['resistance_levels'])
        zone_count = len(data['liquidation_zones'])

        summary_data.append({
            'symbol': symbol,
            'price': data['current_price'],
            'supports': support_count,
            'resistances': resistance_count,
            'zones': zone_count
        })

    # Print formatted table
    print(f"{'Stock':<12} {'Price':<10} {'Supports':<10} {'Resistances':<12} {'Zones':<8}")
    print("-" * 60)
    for item in summary_data:
        print(f"{item['symbol']:<12} Rs.{item['price']:<8.2f} {item['supports']:<10} {item['resistances']:<12} {item['zones']:<8}")

    print(f"\n[OK] Successfully analyzed {len(all_results)}/{len(symbols)} stocks")

    # Save to JSON file
    output_file = 'liquidation_levels_detected.json'
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"[SAVED] Detailed results saved to: {output_file}")

    await db.disconnect()

    print("\n" + "="*80)
    print("[COMPLETE] Liquidation level detection finished!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
