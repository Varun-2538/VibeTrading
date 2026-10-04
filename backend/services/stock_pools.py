"""
Robinhood Stock Tokens, as a source of candles.

No exchange the app reads lists stocks, so a stock's candles are built from the swaps
in its own Uniswap pool on Robinhood Chain - the pool its vault trades through - as
GeckoTerminal indexes them. The pools are the deepest USDG pool per token, the same
tier contracts/src/Addresses.sol routes the vault through; the tokens are pinned to
that file by a test.

Candles here are in the same shape CandleService returns for Binance - time in unix
milliseconds, oldest first - so every detector and the assistant read a stock the way
they read a crypto pair. Volume is the pool's, in US dollars.
"""
from typing import Any, Dict, List, NamedTuple, Optional

GECKO = "https://api.geckoterminal.com/api/v2/networks/robinhood"

# GeckoTerminal serves at most this many candles per request.
GECKO_MAX_LIMIT = 1000


class StockPool(NamedTuple):
    symbol: str
    name: str
    token: str
    pool: str


STOCK_POOLS: Dict[str, StockPool] = {
    s.symbol: s
    for s in (
        StockPool("NVDA", "NVIDIA", "0xd0601CE157Db5bdC3162BbaC2a2C8aF5320D9EEC",
                  "0xd4eb21209c4d6093f80b5b84f5c45cc093ea14a3"),
        StockPool("TSLA", "Tesla", "0x322F0929c4625eD5bAd873c95208D54E1c003b2d",
                  "0xf4acdaeeb7022862a763c9b1b885e11191c889e3"),
        StockPool("AAPL", "Apple", "0xaF3D76f1834A1d425780943C99Ea8A608f8a93f9",
                  "0xaae0d815ee56e4092a5e5c2911e676fea50b2d6d"),
        StockPool("SPY", "S&P 500 ETF", "0x117cc2133c37B721F49dE2A7a74833232B3B4C0C",
                  "0xa7bb1ac63bbab0c44316e6c8c455213441689167"),
        StockPool("QQQ", "Nasdaq-100 ETF", "0xD5f3879160bc7c32ebb4dC785F8a4F505888de68",
                  "0xd60a5d14db690b7afad71f76b108071d7175597d"),
    )
}

# GeckoTerminal's bucket for each timeframe the app serves.
GECKO_TIMEFRAME: Dict[str, tuple] = {
    "1m": ("minute", 1),
    "5m": ("minute", 5),
    "15m": ("minute", 15),
    "1h": ("hour", 1),
    "4h": ("hour", 4),
    "1d": ("day", 1),
}


def stock_pool(symbol: str) -> Optional[StockPool]:
    return STOCK_POOLS.get((symbol or "").upper())


def is_stock(symbol: str) -> bool:
    return stock_pool(symbol) is not None


def ohlcv_request(stock: StockPool, timeframe: str, limit: int) -> tuple:
    """The URL and query for a stock's candles, priced as the stock in dollars."""
    unit, aggregate = GECKO_TIMEFRAME[timeframe]
    params = {
        "aggregate": aggregate,
        "limit": max(1, min(int(limit), GECKO_MAX_LIMIT)),
        "currency": "usd",
        # Price the stock, not the pool's other side.
        "token": stock.token,
    }
    return f"{GECKO}/pools/{stock.pool}/ohlcv/{unit}", params


def parse_ohlcv(body: Any) -> List[Dict[str, Any]]:
    """GeckoTerminal rows arrive newest first as [t_s, o, h, l, c, v]."""
    rows = (((body or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    candles: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            t, o, h, l, c, v = (float(x) for x in row[:6])
        except (TypeError, ValueError):
            continue
        candles[int(t) * 1000] = {"time": int(t) * 1000, "open": o, "high": h, "low": l, "close": c, "volume": v}
    return [candles[t] for t in sorted(candles)]
