from langchain_cerebras import ChatCerebras
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Dict, Any
from datetime import datetime
from config.settings import settings
from mcp_server.client import mcp_client
import json


class IndicatorAgent:
    """
    Indicator Agent - Specialized in analyzing technical indicators
    (RSI, MACD, EMA) for trading signals
    """

    def __init__(self):
        self.llm = ChatCerebras(
            api_key=settings.cerebras_api_key,
            model="llama3.1-8b",  # Fast model for specialized task
            temperature=0.3,  # More deterministic for technical analysis
            max_tokens=1500
        )

        self.system_prompt = """You are the Indicator Agent for tradeSmart.AI, an expert in technical indicator analysis.

Your ONLY job is to analyze technical indicators and provide trading signals:

1. **RSI (Relative Strength Index)** - Identify overbought/oversold conditions:
   - RSI > 70: Overbought (potential reversal down)
   - RSI < 30: Oversold (potential reversal up)
   - RSI 40-60: Neutral zone

2. **MACD (Moving Average Convergence Divergence)** - Identify trend changes:
   - MACD line above signal line: Bullish
   - MACD line below signal line: Bearish
   - Histogram expanding: Momentum increasing
   - Histogram contracting: Momentum decreasing

3. **EMA (Exponential Moving Averages)** - Identify trend direction:
   - Price above EMA 20 > EMA 50: Strong uptrend
   - Price below EMA 20 < EMA 50: Strong downtrend
   - Price between EMAs: Consolidation/ranging

4. **Volume Analysis** - Confirm price moves:
   - Volume > 1.5x average: Strong conviction
   - Volume < 0.5x average: Weak conviction

Return your findings in this EXACT JSON format:
{
    "market_bias": "<bullish|bearish|neutral>",
    "indicators": {
        "rsi": <number>,
        "rsi_signal": "<oversold|neutral|overbought>",
        "macd": {
            "macd_line": <number>,
            "signal_line": <number>,
            "histogram": <number>
        },
        "macd_signal": "<bullish|bearish|neutral>",
        "ema_20": <number>,
        "ema_50": <number>,
        "trend": "<uptrend|downtrend|sideways>",
        "volume_ratio": <number>
    },
    "key_signals": [
        "<actionable signal 1>",
        "<actionable signal 2>",
        ...
    ],
    "confidence": "<high|medium|low>",
    "analysis_summary": "<brief summary of market condition and recommended action>"
}

Be data-driven. Cite specific indicator values. Provide clear, actionable signals."""

    async def analyze(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> Dict[str, Any]:
        """
        Analyze technical indicators for a symbol

        Args:
            symbol: Trading pair (e.g., BTC/USD)
            timeframe: Candle timeframe
            limit: Number of candles to analyze

        Returns:
            Dictionary with indicator analysis and signals
        """
        # Fetch indicator data from MCP
        indicator_data = await mcp_client.calculate_indicators(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit
        )

        # Prepare analysis context
        indicators = indicator_data.get('indicators', {})

        analysis_context = f"""
Symbol: {symbol}
Timeframe: {timeframe}

Current Technical Indicators:

RSI: {indicators.get('rsi', 'N/A')}
RSI Signal: {indicators.get('rsi_signal', 'N/A')}

MACD:
  - MACD Line: {indicators.get('macd', {}).get('macd_line', 'N/A')}
  - Signal Line: {indicators.get('macd', {}).get('signal_line', 'N/A')}
  - Histogram: {indicators.get('macd', {}).get('histogram', 'N/A')}
  - Signal: {indicators.get('macd_signal', 'N/A')}

EMA:
  - EMA 20: {indicators.get('ema_20', 'N/A')}
  - EMA 50: {indicators.get('ema_50', 'N/A')}
  - Trend: {indicators.get('trend', 'N/A')}

Volume:
  - Volume Ratio: {indicators.get('volume_ratio', 'N/A')}x average

Task: Analyze these indicators to determine:
1. Overall market bias (bullish, bearish, or neutral)
2. Key trading signals and entry/exit opportunities
3. Confidence level in the analysis
4. Actionable recommendations for traders
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
                "market_bias": "neutral",
                "indicators": indicators,
                "key_signals": ["Unable to parse detailed signals"],
                "confidence": "medium",
                "analysis_summary": analysis_text
            }

        # Add metadata
        analysis_result['timestamp'] = datetime.utcnow()
        analysis_result['symbol'] = symbol
        analysis_result['timeframe'] = timeframe

        return analysis_result

    def _determine_market_bias(self, indicators: Dict[str, Any]) -> str:
        """
        Determine market bias from indicators (fallback method)

        Args:
            indicators: Indicator data

        Returns:
            Market bias: bullish, bearish, or neutral
        """
        bullish_signals = 0
        bearish_signals = 0

        # RSI check
        rsi = indicators.get('rsi')
        if rsi:
            if rsi < 40:
                bullish_signals += 1
            elif rsi > 60:
                bearish_signals += 1

        # MACD check
        macd_signal = indicators.get('macd_signal')
        if macd_signal == 'bullish':
            bullish_signals += 1
        elif macd_signal == 'bearish':
            bearish_signals += 1

        # Trend check
        trend = indicators.get('trend')
        if trend == 'uptrend':
            bullish_signals += 1
        elif trend == 'downtrend':
            bearish_signals += 1

        if bullish_signals > bearish_signals:
            return 'bullish'
        elif bearish_signals > bullish_signals:
            return 'bearish'
        else:
            return 'neutral'

    def _generate_key_signals(self, indicators: Dict[str, Any], market_bias: str) -> list:
        """
        Generate key trading signals (fallback method)

        Args:
            indicators: Indicator data
            market_bias: Market bias

        Returns:
            List of key signals
        """
        signals = []

        rsi = indicators.get('rsi')
        if rsi:
            if rsi < 30:
                signals.append(f"RSI oversold at {rsi:.1f} - potential bounce")
            elif rsi > 70:
                signals.append(f"RSI overbought at {rsi:.1f} - potential pullback")

        macd_signal = indicators.get('macd_signal')
        if macd_signal:
            signals.append(f"MACD showing {macd_signal} momentum")

        trend = indicators.get('trend')
        if trend:
            signals.append(f"Price action indicates {trend}")

        volume_ratio = indicators.get('volume_ratio', 1.0)
        if volume_ratio > 1.5:
            signals.append(f"High volume confirmation ({volume_ratio:.1f}x)")

        if not signals:
            signals.append("Mixed signals - wait for clearer setup")

        return signals
