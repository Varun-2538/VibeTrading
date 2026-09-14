import json
from typing import Dict, Any
from services.market_data_service import MarketDataService


async def calculate_indicators_tool(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 240
) -> str:
    """
    MCP Tool: Calculate technical indicators (RSI, MACD, EMA)

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        limit: Number of candles for calculation

    Returns:
        JSON string with calculated indicators
    """
    try:
        indicators = await MarketDataService.calculate_technical_indicators(
            symbol, timeframe, limit
        )

        result = {
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "indicators": indicators
        }

        return json.dumps(result)

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "symbol": symbol
        }
        return json.dumps(error_result)


# Tool metadata for MCP server registration
TOOL_METADATA = {
    "name": "calculate_indicators",
    "description": "Calculate technical indicators including RSI, MACD, EMA for trading analysis",
    "inputSchema": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Trading pair symbol"
            },
            "timeframe": {
                "type": "string",
                "description": "Candlestick timeframe",
                "enum": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                "default": "1h"
            },
            "limit": {
                "type": "integer",
                "description": "Number of candles for calculation",
                "default": 240
            }
        },
        "required": ["symbol"]
    }
}
