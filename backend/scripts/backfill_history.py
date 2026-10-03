"""
Fill or top up candle history by hand.

    python -m scripts.backfill_history                      # everything
    python -m scripts.backfill_history --symbol BTCUSDT --timeframe 1h

The worker does the same thing hourly; this is for the first fill on a new
machine and for repairing one series without waiting.
"""
import argparse
import asyncio

from models.database import db
from services.candle_service import _http, close_http
from services.history_service import PAIRS, TIMEFRAME_MS, topup_all
from worker import summarise


async def run(symbols, timeframes) -> None:
    await db.connect()
    await db.bootstrap_schema()
    try:
        client = await _http()
        results = await topup_all(client=client, pairs=tuple(symbols), timeframes=tuple(timeframes))
        for r in results:
            print(f"{r.symbol:9} {r.timeframe:4} pages={r.pages:4} bars={r.bars:7} {r.error or ''}")
        print(summarise(results))
    finally:
        await close_http()
        await db.disconnect()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=PAIRS, action="append")
    parser.add_argument("--timeframe", choices=tuple(TIMEFRAME_MS), action="append")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.symbol or PAIRS, args.timeframe or tuple(TIMEFRAME_MS)))
