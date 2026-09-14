from mcp.server import Server
from mcp.types import Tool, TextContent
import json
from typing import Any
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all MCP tools
from mcp_server.tools.ohlc_tool import get_ohlc_data_tool, TOOL_METADATA as OHLC_METADATA
from mcp_server.tools.indicator_tool import calculate_indicators_tool, TOOL_METADATA as INDICATOR_METADATA
from mcp_server.tools.liquidation_tool import detect_liquidation_levels_tool, TOOL_METADATA as LIQUIDATION_METADATA
from mcp_server.tools.annotation_tool import (
    create_chart_annotation_tool,
    create_liquidation_zone_tool,
    ANNOTATION_TOOL_METADATA,
    LIQUIDATION_ZONE_TOOL_METADATA
)
from mcp_server.tools.strategy_tool import generate_strategy_tool, TOOL_METADATA as STRATEGY_METADATA


def create_mcp_server() -> Server:
    """
    Create and configure MCP server with all tools

    Returns:
        Configured MCP Server instance
    """
    app = Server("tradesmart-mcp")

    # Register Tool 1: Get OHLC Data
    @app.tool()
    async def get_ohlc_data(
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> str:
        """Fetch OHLC data from TimescaleDB"""
        return await get_ohlc_data_tool(symbol, timeframe, limit)

    # Register Tool 2: Calculate Indicators
    @app.tool()
    async def calculate_indicators(
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> str:
        """Calculate technical indicators (RSI, MACD, EMA)"""
        return await calculate_indicators_tool(symbol, timeframe, limit)

    # Register Tool 3: Detect Liquidation Levels
    @app.tool()
    async def detect_liquidation_levels(
        symbol: str,
        timeframe: str = "1h",
        lookback_periods: int = 240
    ) -> str:
        """Detect liquidation levels and support/resistance zones"""
        return await detect_liquidation_levels_tool(symbol, timeframe, lookback_periods)

    # Register Tool 4: Create Chart Annotation
    @app.tool()
    async def create_chart_annotation(
        symbol: str,
        annotation_type: str,
        coordinates: dict,
        style: dict,
        label: str
    ) -> str:
        """Create chart annotation (rectangle, line, arrow, text)"""
        return await create_chart_annotation_tool(
            symbol, annotation_type, coordinates, style, label
        )

    # Register Tool 5: Create Liquidation Zone
    @app.tool()
    async def create_liquidation_zone(
        symbol: str,
        start_price: float,
        end_price: float,
        start_time: int,
        end_time: int,
        label: str = "Liquidation Zone",
        strength: str = "medium"
    ) -> str:
        """Create liquidation zone rectangle annotation"""
        return await create_liquidation_zone_tool(
            symbol, start_price, end_price, start_time, end_time, label, strength
        )

    # Register Tool 6: Generate Strategy
    @app.tool()
    async def generate_strategy(
        prompt: str,
        symbol: str,
        timeframe: str,
        liquidation_analysis: dict,
        indicator_analysis: dict
    ) -> str:
        """Generate trading strategy from analyses"""
        return await generate_strategy_tool(
            prompt, symbol, timeframe, liquidation_analysis, indicator_analysis
        )

    return app


# For running standalone MCP server
if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server

    async def main():
        """Main entry point for standalone MCP server"""
        app = create_mcp_server()

        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )

    asyncio.run(main())
