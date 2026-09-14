import json
from typing import Dict, Any
from services.market_data_service import MarketDataService


async def get_ohlc_data_tool(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 240
) -> str:
    """
    MCP Tool: Fetch OHLC data from TimescaleDB

    Args:
        symbol: Trading pair (e.g., "BTC/USD")
        timeframe: Candle timeframe (default: "1h")
        limit: Number of candles to fetch (default: 240 for 10 days)

    Returns:
        JSON string with OHLC data
    """
    try:
        data = await MarketDataService.get_ohlc_data(symbol, timeframe, limit)

        result = {
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(data),
            "data": data
        }

        return json.dumps(result)

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "symbol": symbol,
            "timeframe": timeframe
        }
        return json.dumps(error_result)


# Tool metadata for MCP server registration
TOOL_METADATA = {
    "name": "get_ohlc_data",
    "description": "Fetch OHLC (Open, High, Low, Close) candlestick data from TimescaleDB for technical analysis",
    "inputSchema": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Trading pair symbol (e.g., BTC/USD, ETH/USD)"
            },
            "timeframe": {
                "type": "string",
                "description": "Candlestick timeframe",
                "enum": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                "default": "1h"
            },
            "limit": {
                "type": "integer",
                "description": "Number of candles to fetch",
                "default": 240,
                "minimum": 1,
                "maximum": 1000
            }
        },
        "required": ["symbol"]
    }
}
