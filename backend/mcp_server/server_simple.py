"""
Simplified MCP Server for TradeSmart.AI
Compatible with mcp library 1.12.4+
"""
from mcp.server import Server
from mcp import types
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server.tools.ohlc_tool import get_ohlc_data_tool
from mcp_server.tools.indicator_tool import calculate_indicators_tool
from mcp_server.tools.liquidation_tool import detect_liquidation_levels_tool
from mcp_server.tools.annotation_tool import create_chart_annotation_tool, create_liquidation_zone_tool
from mcp_server.tools.strategy_tool import generate_strategy_tool


# Create server instance
server = Server("tradesmart-mcp")


# Register list_tools handler
@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available tools"""
    return [
        types.Tool(
            name="get_ohlc_data",
            description="Fetch OHLC (Open, High, Low, Close) data from database",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock symbol (e.g., RELIANCE, TCS)"},
                    "timeframe": {"type": "string", "description": "Timeframe (1m, 5m, 15m, 1h, 4h, 1d)", "default": "1h"},
                    "limit": {"type": "integer", "description": "Number of candles to fetch", "default": 240}
                },
                "required": ["symbol"]
            }
        ),
        types.Tool(
            name="calculate_indicators",
            description="Calculate technical indicators (RSI, MACD, EMA)",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "timeframe": {"type": "string", "default": "1h"},
                    "limit": {"type": "integer", "default": 240}
                },
                "required": ["symbol"]
            }
        ),
        types.Tool(
            name="detect_liquidation_levels",
            description="Detect support/resistance and liquidation zones",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "timeframe": {"type": "string", "default": "1h"},
                    "lookback_periods": {"type": "integer", "default": 240}
                },
                "required": ["symbol"]
            }
        ),
        types.Tool(
            name="create_chart_annotation",
            description="Create chart annotation (rectangle, line, arrow, text)",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "annotation_type": {"type": "string"},
                    "coordinates": {"type": "object"},
                    "style": {"type": "object"},
                    "label": {"type": "string"}
                },
                "required": ["symbol", "annotation_type", "coordinates", "style", "label"]
            }
        ),
        types.Tool(
            name="create_liquidation_zone",
            description="Create liquidation zone rectangle annotation",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "start_price": {"type": "number"},
                    "end_price": {"type": "number"},
                    "start_time": {"type": "integer"},
                    "end_time": {"type": "integer"},
                    "label": {"type": "string", "default": "Liquidation Zone"},
                    "strength": {"type": "string", "default": "medium"}
                },
                "required": ["symbol", "start_price", "end_price", "start_time", "end_time"]
            }
        ),
        types.Tool(
            name="generate_strategy",
            description="Generate trading strategy from analyses",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "symbol": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "liquidation_analysis": {"type": "object"},
                    "indicator_analysis": {"type": "object"}
                },
                "required": ["prompt", "symbol", "timeframe", "liquidation_analysis", "indicator_analysis"]
            }
        )
    ]


# Register call_tool handler
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Handle tool calls"""

    result = None

    if name == "get_ohlc_data":
        result = await get_ohlc_data_tool(
            symbol=arguments.get("symbol"),
            timeframe=arguments.get("timeframe", "1h"),
            limit=arguments.get("limit", 240)
        )
    elif name == "calculate_indicators":
        result = await calculate_indicators_tool(
            symbol=arguments.get("symbol"),
            timeframe=arguments.get("timeframe", "1h"),
            limit=arguments.get("limit", 240)
        )
    elif name == "detect_liquidation_levels":
        result = await detect_liquidation_levels_tool(
            symbol=arguments.get("symbol"),
            timeframe=arguments.get("timeframe", "1h"),
            lookback_periods=arguments.get("lookback_periods", 240)
        )
    elif name == "create_chart_annotation":
        result = await create_chart_annotation_tool(
            symbol=arguments.get("symbol"),
            annotation_type=arguments.get("annotation_type"),
            coordinates=arguments.get("coordinates"),
            style=arguments.get("style"),
            label=arguments.get("label")
        )
    elif name == "create_liquidation_zone":
        result = await create_liquidation_zone_tool(
            symbol=arguments.get("symbol"),
            start_price=arguments.get("start_price"),
            end_price=arguments.get("end_price"),
            start_time=arguments.get("start_time"),
            end_time=arguments.get("end_time"),
            label=arguments.get("label", "Liquidation Zone"),
            strength=arguments.get("strength", "medium")
        )
    elif name == "generate_strategy":
        result = await generate_strategy_tool(
            prompt=arguments.get("prompt"),
            symbol=arguments.get("symbol"),
            timeframe=arguments.get("timeframe"),
            liquidation_analysis=arguments.get("liquidation_analysis"),
            indicator_analysis=arguments.get("indicator_analysis")
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    # Return result as TextContent
    return [types.TextContent(
        type="text",
        text=json.dumps(result) if isinstance(result, dict) else str(result)
    )]


# Main entry point for standalone server
async def main():
    """Run MCP server via stdio"""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
