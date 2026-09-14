from langchain_cerebras import ChatCerebras
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Dict, Any
from datetime import datetime
from config.settings import settings
from agents.liquidation_agent import LiquidationAgent
from agents.indicator_agent import IndicatorAgent
from mcp_server.client import mcp_client
import asyncio
import json


class OrchestratorAgent:
    """
    Orchestrator Agent - Coordinates specialized agents and synthesizes
    their findings into actionable trading strategies
    """

    def __init__(self):
        self.llm = ChatCerebras(
            api_key=settings.cerebras_api_key,
            model="llama3.1-70b",  # Larger model for orchestration
            temperature=0.7,  # More creative for strategy synthesis
            max_tokens=2500
        )

        self.liquidation_agent = LiquidationAgent()
        self.indicator_agent = IndicatorAgent()

        self.system_prompt = """You are the Orchestrator Agent for tradeSmart.AI, the master coordinator of AI trading analysis.

Your role is to:
1. Understand user prompts about trading strategies
2. Coordinate specialized agents (Liquidation Agent, Indicator Agent)
3. Synthesize their findings into comprehensive, actionable trading strategies
4. Ensure all analysis is complete before generating final strategy

You have access to two specialized agents:
- **Liquidation Agent**: Identifies support/resistance and liquidation zones where price reversals are likely
- **Indicator Agent**: Analyzes technical indicators (RSI, MACD, EMA) for momentum and trend signals

When building a strategy:
1. Review the Liquidation Agent's findings for key price levels and zones
2. Review the Indicator Agent's findings for momentum and trend confirmation
3. Combine both analyses to create a coherent strategy with:
   - Clear entry conditions (when to enter the trade)
   - Clear exit conditions (when to exit - both profit and loss)
   - Risk management parameters (stop-loss, take-profit, position sizing)
   - Reasoning that explains WHY this strategy makes sense

Return your strategy in this EXACT JSON format:
{
    "strategy_type": "<swing|scalp|day_trade|position>",
    "entry_conditions": [
        {"description": "<condition>", "parameters": {<key>: <value>}}
    ],
    "exit_conditions": [
        {"description": "<condition>", "parameters": {<key>: <value>}}
    ],
    "risk_management": {
        "stop_loss": <price>,
        "take_profit": [<price1>, <price2>],
        "position_size_pct": <percentage>,
        "risk_reward_ratio": <ratio>
    },
    "reasoning": "<detailed explanation of why this strategy works>",
    "confidence_score": <0.0-1.0>
}

Always be precise, data-driven, and actionable. Focus on creating strategies that are practical and executable."""

    async def build_strategy(
        self,
        user_prompt: str,
        symbol: str,
        timeframe: str = "1h",
        risk_tolerance: str = "medium"
    ) -> Dict[str, Any]:
        """
        Build a complete trading strategy from user prompt

        Args:
            user_prompt: User's natural language strategy request
            symbol: Trading pair
            timeframe: Candle timeframe
            risk_tolerance: Risk tolerance level

        Returns:
            Complete strategy with all analyses
        """
        start_time = datetime.utcnow()

        # Step 1: Run specialized agents in PARALLEL for speed
        liquidation_task = asyncio.create_task(
            self.liquidation_agent.analyze(symbol, timeframe)
        )
        indicator_task = asyncio.create_task(
            self.indicator_agent.analyze(symbol, timeframe)
        )

        # Wait for both agents
        liquidation_analysis, indicator_analysis = await asyncio.gather(
            liquidation_task,
            indicator_task
        )

        # Step 2: Synthesize findings into strategy
        synthesis_context = f"""
User Request: {user_prompt}
Symbol: {symbol}
Timeframe: {timeframe}
Risk Tolerance: {risk_tolerance}

=== LIQUIDATION AGENT FINDINGS ===
{json.dumps(liquidation_analysis, indent=2, default=str)}

=== INDICATOR AGENT FINDINGS ===
{json.dumps(indicator_analysis, indent=2, default=str)}

Task: Create a complete trading strategy that:
1. Aligns with the user's request
2. Uses liquidation levels for entry/exit price targets
3. Uses indicator signals for timing and confirmation
4. Includes proper risk management
5. Is practical and executable

Generate the strategy now."""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=synthesis_context)
        ]

        response = await self.llm.ainvoke(messages)
        strategy_text = response.content

        # Parse strategy JSON
        try:
            # Extract JSON from response
            if "```json" in strategy_text:
                json_start = strategy_text.find("```json") + 7
                json_end = strategy_text.find("```", json_start)
                strategy_text = strategy_text[json_start:json_end].strip()
            elif "```" in strategy_text:
                json_start = strategy_text.find("```") + 3
                json_end = strategy_text.find("```", json_start)
                strategy_text = strategy_text[json_start:json_end].strip()

            strategy_data = json.loads(strategy_text)
        except json.JSONDecodeError:
            # Fallback - use service layer to build strategy
            from services.strategy_service import StrategyService
            strategy_obj = await StrategyService.build_strategy(
                prompt=user_prompt,
                symbol=symbol,
                timeframe=timeframe,
                liquidation_analysis=liquidation_analysis,
                indicator_analysis=indicator_analysis
            )
            strategy_data = strategy_obj.model_dump()

        # Step 3: Create chart annotations for liquidation zones
        annotation_ids = await self.liquidation_agent.create_annotations(
            symbol=symbol,
            analysis_result=liquidation_analysis,
            timeframe=timeframe
        )

        # Calculate execution time
        end_time = datetime.utcnow()
        execution_time = (end_time - start_time).total_seconds()

        # Build final response
        result = {
            "success": True,
            "strategy": strategy_data,
            "liquidation_analysis": liquidation_analysis,
            "indicator_analysis": indicator_analysis,
            "chart_annotations": annotation_ids,
            "execution_time_seconds": round(execution_time, 2),
            "timestamp": datetime.utcnow()
        }

        return result

    async def quick_analysis(
        self,
        symbol: str,
        timeframe: str = "1h"
    ) -> Dict[str, Any]:
        """
        Quick market analysis without full strategy building

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe

        Returns:
            Quick analysis summary
        """
        # Run agents in parallel
        liquidation_task = asyncio.create_task(
            self.liquidation_agent.analyze(symbol, timeframe)
        )
        indicator_task = asyncio.create_task(
            self.indicator_agent.analyze(symbol, timeframe)
        )

        liquidation_analysis, indicator_analysis = await asyncio.gather(
            liquidation_task,
            indicator_task
        )

        return {
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "market_bias": indicator_analysis.get('market_bias'),
            "key_support": liquidation_analysis.get('support_levels', [])[:2],
            "key_resistance": liquidation_analysis.get('resistance_levels', [])[:2],
            "key_signals": indicator_analysis.get('key_signals', []),
            "timestamp": datetime.utcnow()
        }
