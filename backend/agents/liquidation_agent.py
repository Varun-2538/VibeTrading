from langchain_cerebras import ChatCerebras
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Dict, Any
from datetime import datetime
from config.settings import settings
from mcp_server.client import mcp_client
import json


class LiquidationAgent:
    """
    Liquidation Agent - Specialized in detecting support/resistance
    and liquidation zones
    """

    def __init__(self):
        self.llm = ChatCerebras(
            api_key=settings.cerebras_api_key,
            model="llama3.1-8b",  # Fast model for specialized task
            temperature=0.3,  # More deterministic for technical analysis
            max_tokens=1500
        )

        self.system_prompt = """You are the Liquidation Agent for tradeSmart.AI, an expert in identifying price levels where liquidations occur.

Your ONLY job is to identify:
1. Major support levels (where buyers step in and liquidations might trigger on the downside)
2. Major resistance levels (where sellers step in and liquidations might trigger on the upside)
3. Liquidation zones (price areas with high stop-loss clusters and potential cascade liquidations)

Analysis process:
1. Analyze historical price levels to find areas of high liquidity
2. Identify price levels that have been tested multiple times
3. Determine the strength of each level (weak, medium, strong) based on:
   - Number of times price tested the level
   - Volume at those levels
   - Proximity to current price
   - Historical reactions at those levels

Return your findings in this EXACT JSON format:
{
    "support_levels": [
        {"price": <number>, "strength": "<weak|medium|strong>", "reasoning": "<brief explanation>"},
        ...
    ],
    "resistance_levels": [
        {"price": <number>, "strength": "<weak|medium|strong>", "reasoning": "<brief explanation>"},
        ...
    ],
    "liquidation_zones": [
        {"start_price": <number>, "end_price": <number>, "strength": "<weak|medium|strong>", "label": "<description>"},
        ...
    ],
    "analysis_summary": "<brief summary of key findings>"
}

Be precise with numbers. Focus on actionable levels. No speculation - only data-driven analysis."""

    async def analyze(
        self,
        symbol: str,
        timeframe: str = "1h",
        lookback_periods: int = 240
    ) -> Dict[str, Any]:
        """
        Analyze liquidation levels for a symbol

        Args:
            symbol: Trading pair (e.g., BTC/USD)
            timeframe: Candle timeframe
            lookback_periods: Number of periods to analyze

        Returns:
            Dictionary with support, resistance, and liquidation zones
        """
        # Fetch liquidation data from MCP
        liquidation_data = await mcp_client.detect_liquidation_levels(
            symbol=symbol,
            timeframe=timeframe,
            lookback_periods=lookback_periods
        )

        # Fetch OHLC data for context
        ohlc_data = await mcp_client.get_ohlc_data(
            symbol=symbol,
            timeframe=timeframe,
            limit=min(lookback_periods, 100)  # Limit for context
        )

        # Prepare analysis context
        analysis_context = f"""
Symbol: {symbol}
Timeframe: {timeframe}
Current Price: ${liquidation_data.get('current_price', 'N/A')}

Detected Support Levels:
{json.dumps(liquidation_data.get('support_levels', []), indent=2)}

Detected Resistance Levels:
{json.dumps(liquidation_data.get('resistance_levels', []), indent=2)}

Recent Price Action (last 20 candles):
{json.dumps(ohlc_data.get('data', [])[-20:] if ohlc_data.get('data') else [], indent=2)}

Task: Analyze these levels and identify the most significant liquidation zones where cascading liquidations are likely to occur. Consider price clustering, historical reactions, and current market structure.
"""

        # Call LLM for analysis
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=analysis_context)
        ]

        response = await self.llm.ainvoke(messages)
        analysis_text = response.content

        # Parse JSON response
        try:
            # Extract JSON from response (handle markdown code blocks)
            if "```json" in analysis_text:
                json_start = analysis_text.find("```json") + 7
                json_end = analysis_text.find("```", json_start)
                analysis_text = analysis_text[json_start:json_end].strip()
            elif "```" in analysis_text:
                json_start = analysis_text.find("```") + 3
                json_end = analysis_text.find("```", json_start)
                analysis_text = analysis_text[json_start:json_end].strip()

            analysis_result = json.loads(analysis_text)
        except json.JSONDecodeError:
            # Fallback to structured data if LLM didn't return proper JSON
            analysis_result = {
                "support_levels": liquidation_data.get('support_levels', []),
                "resistance_levels": liquidation_data.get('resistance_levels', []),
                "liquidation_zones": [],
                "analysis_summary": analysis_text
            }

        # Add metadata
        analysis_result['timestamp'] = datetime.utcnow()
        analysis_result['symbol'] = symbol
        analysis_result['timeframe'] = timeframe
        analysis_result['current_price'] = liquidation_data.get('current_price')

        return analysis_result

    async def create_annotations(
        self,
        symbol: str,
        analysis_result: Dict[str, Any],
        timeframe: str = "1h"
    ) -> list:
        """
        Create chart annotations for liquidation zones

        Args:
            symbol: Trading pair
            analysis_result: Analysis result from analyze()
            timeframe: Timeframe

        Returns:
            List of created annotation IDs
        """
        annotation_ids = []

        # Get current time for annotation timerange
        current_time = int(datetime.utcnow().timestamp())
        time_range = 86400 * 10  # 10 days in seconds

        # Create annotations for liquidation zones
        for zone in analysis_result.get('liquidation_zones', []):
            try:
                result = await mcp_client.create_liquidation_zone(
                    symbol=symbol,
                    start_price=zone.get('start_price'),
                    end_price=zone.get('end_price'),
                    start_time=current_time - time_range,
                    end_time=current_time,
                    label=zone.get('label', 'Liquidation Zone'),
                    strength=zone.get('strength', 'medium')
                )
                if result.get('success'):
                    annotation_ids.append(result.get('annotation_id'))
            except Exception as e:
                print(f"Error creating annotation: {e}")

        return annotation_ids
