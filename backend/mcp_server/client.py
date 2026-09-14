from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typing import Any, Dict, Optional, List
import json


class MCPClient:
    """Client for communicating with MCP server"""

    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.read = None
        self.write = None
        self.context = None

    async def connect(self):
        """Connect to MCP server"""
        server_params = StdioServerParameters(
            command="python",
            args=["mcp_server/server_simple.py"],
            env=None
        )

        self.context = stdio_client(server_params)
        self.read, self.write = await self.context.__aenter__()

        session_context = ClientSession(self.read, self.write)
        self.session = await session_context.__aenter__()

        # Initialize the session
        await self.session.initialize()

    async def disconnect(self):
        """Disconnect from MCP server"""
        if self.session:
            await self.session.__aexit__(None, None, None)
        if self.context:
            await self.context.__aexit__(None, None, None)

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Call an MCP tool

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result (parsed from JSON if possible)
        """
        if not self.session:
            raise RuntimeError("MCP client not connected. Call connect() first.")

        result = await self.session.call_tool(tool_name, arguments)

        # Extract text content from result
        if result.content and len(result.content) > 0:
            text_content = result.content[0].text
            try:
                return json.loads(text_content)
            except json.JSONDecodeError:
                return text_content

        return None

    async def get_ohlc_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> Dict[str, Any]:
        """Fetch OHLC data via MCP"""
        return await self.call_tool("get_ohlc_data", {
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit
        })

    async def calculate_indicators(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> Dict[str, Any]:
        """Calculate technical indicators via MCP"""
        return await self.call_tool("calculate_indicators", {
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit
        })

    async def detect_liquidation_levels(
        self,
        symbol: str,
        timeframe: str = "1h",
        lookback_periods: int = 240
    ) -> Dict[str, Any]:
        """Detect liquidation levels via MCP"""
        return await self.call_tool("detect_liquidation_levels", {
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback_periods": lookback_periods
        })

    async def create_chart_annotation(
        self,
        symbol: str,
        annotation_type: str,
        coordinates: Dict[str, Any],
        style: Dict[str, Any],
        label: str
    ) -> Dict[str, Any]:
        """Create chart annotation via MCP"""
        return await self.call_tool("create_chart_annotation", {
            "symbol": symbol,
            "annotation_type": annotation_type,
            "coordinates": coordinates,
            "style": style,
            "label": label
        })

    async def create_liquidation_zone(
        self,
        symbol: str,
        start_price: float,
        end_price: float,
        start_time: int,
        end_time: int,
        label: str = "Liquidation Zone",
        strength: str = "medium"
    ) -> Dict[str, Any]:
        """Create liquidation zone annotation via MCP"""
        return await self.call_tool("create_liquidation_zone", {
            "symbol": symbol,
            "start_price": start_price,
            "end_price": end_price,
            "start_time": start_time,
            "end_time": end_time,
            "label": label,
            "strength": strength
        })

    async def generate_strategy(
        self,
        prompt: str,
        symbol: str,
        timeframe: str,
        liquidation_analysis: Dict[str, Any],
        indicator_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate trading strategy via MCP"""
        return await self.call_tool("generate_strategy", {
            "prompt": prompt,
            "symbol": symbol,
            "timeframe": timeframe,
            "liquidation_analysis": liquidation_analysis,
            "indicator_analysis": indicator_analysis
        })

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List all available MCP tools"""
        if not self.session:
            raise RuntimeError("MCP client not connected. Call connect() first.")

        tools = await self.session.list_tools()
        return [{"name": tool.name, "description": tool.description} for tool in tools.tools]


# Global MCP client instance
mcp_client = MCPClient()
