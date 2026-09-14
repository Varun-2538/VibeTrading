import json
from typing import Dict, Any
from services.market_data_service import MarketDataService


async def detect_liquidation_levels_tool(
    symbol: str,
    timeframe: str = "1h",
    lookback_periods: int = 240
) -> str:
    """
    MCP Tool: Detect liquidation levels (support/resistance zones)

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        lookback_periods: Number of periods to analyze

    Returns:
        JSON string with detected liquidation levels
    """
    try:
        liquidation_data = await MarketDataService.detect_liquidation_levels(
            symbol, timeframe, lookback_periods
        )

        result = {
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": liquidation_data.get('current_price'),
            "support_levels": liquidation_data.get('support_levels', []),
            "resistance_levels": liquidation_data.get('resistance_levels', [])
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
    "name": "detect_liquidation_levels",
    "description": "Detect liquidation levels, support and resistance zones from historical price action",
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
            "lookback_periods": {
                "type": "integer",
                "description": "Number of periods to analyze for levels",
                "default": 240
            }
        },
        "required": ["symbol"]
    }
}
