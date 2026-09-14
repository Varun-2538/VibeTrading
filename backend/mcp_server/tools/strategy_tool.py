import json
from typing import Dict, Any
from services.strategy_service import StrategyService


async def generate_strategy_tool(
    prompt: str,
    symbol: str,
    timeframe: str,
    liquidation_analysis: Dict[str, Any],
    indicator_analysis: Dict[str, Any]
) -> str:
    """
    MCP Tool: Generate trading strategy from analyses

    Args:
        prompt: User's strategy prompt
        symbol: Trading pair
        timeframe: Candle timeframe
        liquidation_analysis: Analysis from liquidation agent
        indicator_analysis: Analysis from indicator agent

    Returns:
        JSON string with generated strategy
    """
    try:
        strategy = await StrategyService.build_strategy(
            prompt=prompt,
            symbol=symbol,
            timeframe=timeframe,
            liquidation_analysis=liquidation_analysis,
            indicator_analysis=indicator_analysis
        )

        result = {
            "success": True,
            "strategy": strategy.model_dump(),
            "symbol": symbol,
            "timeframe": timeframe
        }

        return json.dumps(result, default=str)

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "symbol": symbol
        }
        return json.dumps(error_result)


# Tool metadata for MCP server registration
TOOL_METADATA = {
    "name": "generate_strategy",
    "description": "Generate a complete trading strategy by combining liquidation and indicator analyses",
    "inputSchema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "User's natural language strategy request"
            },
            "symbol": {
                "type": "string",
                "description": "Trading pair symbol"
            },
            "timeframe": {
                "type": "string",
                "description": "Candlestick timeframe",
                "enum": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
            },
            "liquidation_analysis": {
                "type": "object",
                "description": "Analysis results from liquidation agent"
            },
            "indicator_analysis": {
                "type": "object",
                "description": "Analysis results from indicator agent"
            }
        },
        "required": ["prompt", "symbol", "timeframe", "liquidation_analysis", "indicator_analysis"]
    }
}
