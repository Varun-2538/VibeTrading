"""
Chat Controller - Handles user queries about stocks via AI agents
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from agents.orchestrator import OrchestratorAgent
from agents.liquidation_agent import LiquidationAgent
from agents.indicator_agent import IndicatorAgent
from services.market_data_service import MarketDataService
from repositories.ohlc_repository import OHLCRepository
from decimal import Decimal
import re


def to_float(value):
    """Convert Decimal to float safely"""
    if isinstance(value, Decimal):
        return float(value)
    return value


router = APIRouter(prefix="/api/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    message: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = "1h"


class ChatResponse(BaseModel):
    response: str
    symbol: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    chart_update: Optional[bool] = False


# Initialize agents
liquidation_agent = LiquidationAgent()
indicator_agent = IndicatorAgent()
orchestrator = OrchestratorAgent()


def extract_symbol_from_message(message: str) -> Optional[str]:
    """Extract crypto symbol from user message"""
    message_upper = message.upper()

    # List of crypto pairs we have
    crypto_pairs = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT"
    ]

    # Mapping short forms to full symbols
    crypto_map = {
        "BTC": "BTCUSDT", "BITCOIN": "BTCUSDT",
        "ETH": "ETHUSDT", "ETHEREUM": "ETHUSDT",
        "BNB": "BNBUSDT", "BINANCE": "BNBUSDT",
        "SOL": "SOLUSDT", "SOLANA": "SOLUSDT",
        "XRP": "XRPUSDT", "RIPPLE": "XRPUSDT",
        "ADA": "ADAUSDT", "CARDANO": "ADAUSDT",
        "DOGE": "DOGEUSDT", "DOGECOIN": "DOGEUSDT",
        "DOT": "DOTUSDT", "POLKADOT": "DOTUSDT",
        "AVAX": "AVAXUSDT", "AVALANCHE": "AVAXUSDT"
    }

    # Check for full symbol
    for crypto in crypto_pairs:
        if crypto in message_upper:
            return crypto

    # Check for short form
    for short_form, full_symbol in crypto_map.items():
        if short_form in message_upper:
            return full_symbol

    return None


def detect_query_intent(message: str) -> str:
    """Detect what the user is asking about"""
    message_lower = message.lower()

    if any(word in message_lower for word in ['support', 'resistance', 'liquidity', 'level']):
        return 'liquidity_levels'
    elif any(word in message_lower for word in ['indicator', 'rsi', 'macd', 'ema']):
        return 'technical_indicators'
    elif any(word in message_lower for word in ['strategy', 'trade', 'buy', 'sell', 'entry', 'exit']):
        return 'trading_strategy'
    elif any(word in message_lower for word in ['price', 'current', 'value']):
        return 'current_price'
    else:
        return 'general'


@router.post("/ask", response_model=ChatResponse)
async def ask_question(request: ChatRequest):
    """
    Handle user questions about cryptocurrencies

    Example queries:
    - "What are the liquidity levels for Bitcoin?"
    - "Show me support and resistance for ETH"
    - "Give me a trading strategy for BTC"
    """
    try:
        message = request.message

        # Extract symbol from message or use provided symbol
        symbol = request.symbol or extract_symbol_from_message(message)

        if not symbol:
            return ChatResponse(
                response="Please specify a cryptocurrency. Available: Bitcoin (BTC), Ethereum (ETH), Binance Coin (BNB), Solana (SOL), Ripple (XRP), Cardano (ADA), Dogecoin (DOGE), Polkadot (DOT), Avalanche (AVAX)",
                symbol=None,
                chart_update=False
            )

        # Detect query intent
        intent = detect_query_intent(message)

        # Get current price
        ohlc_data = await OHLCRepository.get_ohlc_data(symbol, request.timeframe, limit=1)
        if not ohlc_data:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

        current_price = float(ohlc_data[0]['close'])

        # Handle different query types
        if intent == 'liquidity_levels':
            # Get liquidity levels (support/resistance)
            levels = await MarketDataService.detect_liquidation_levels(
                symbol=symbol,
                timeframe=request.timeframe,
                lookback_periods=100
            )

            support_levels = levels.get('support_levels', [])
            resistance_levels = levels.get('resistance_levels', [])

            # Format response
            response_text = f"**{symbol} Liquidity Levels Analysis**\n\n"
            response_text += f"Current Price: ${current_price:,.2f}\n\n"

            if support_levels:
                response_text += "🟢 **Support Levels** (Buy zones):\n"
                for i, level in enumerate(support_levels[:3], 1):
                    level_price = to_float(level['price'])
                    distance = ((current_price - level_price) / current_price) * 100
                    response_text += f"{i}. ${level_price:,.2f} ({level['strength']}) - {distance:+.2f}% from current\n"
                response_text += "\n"

            if resistance_levels:
                response_text += "🔴 **Resistance Levels** (Sell zones):\n"
                for i, level in enumerate(resistance_levels[:3], 1):
                    level_price = to_float(level['price'])
                    distance = ((level_price - current_price) / current_price) * 100
                    response_text += f"{i}. ${level_price:,.2f} ({level['strength']}) - {distance:+.2f}% from current\n"

            # Convert all Decimals to floats for JSON serialization
            def convert_level(level):
                return {
                    'price': to_float(level.get('price')),
                    'strength': level.get('strength'),
                    'test_count': level.get('test_count', 0)
                }

            return ChatResponse(
                response=response_text,
                symbol=symbol,
                data={
                    'current_price': current_price,
                    'support_levels': [convert_level(l) for l in support_levels[:5]],
                    'resistance_levels': [convert_level(l) for l in resistance_levels[:5]]
                },
                chart_update=True
            )

        elif intent == 'technical_indicators':
            # Get technical indicators
            indicators = await MarketDataService.calculate_indicators(
                symbol=symbol,
                timeframe=request.timeframe,
                limit=50
            )

            response_text = f"**{symbol} Technical Indicators**\n\n"
            response_text += f"Current Price: ${current_price:,.2f}\n\n"

            if indicators.get('rsi'):
                rsi = indicators['rsi']
                rsi_signal = indicators.get('rsi_signal', 'neutral')
                response_text += f"📈 **RSI**: {rsi:.2f} - {rsi_signal.upper()}\n"
                if rsi > 70:
                    response_text += "   ⚠️ Overbought - Potential reversal down\n"
                elif rsi < 30:
                    response_text += "   ✅ Oversold - Potential reversal up\n"
                response_text += "\n"

            if indicators.get('macd'):
                macd = indicators['macd']
                response_text += f"📉 **MACD**:\n"
                response_text += f"   MACD Line: {macd.get('macd_line', 0):.2f}\n"
                response_text += f"   Signal Line: {macd.get('signal_line', 0):.2f}\n"
                response_text += f"   Signal: {indicators.get('macd_signal', 'neutral').upper()}\n\n"

            if indicators.get('ema'):
                ema = indicators['ema']
                response_text += f"📊 **EMA**:\n"
                response_text += f"   EMA 20: ${ema.get('ema_20', 0):,.2f}\n"
                response_text += f"   EMA 50: ${ema.get('ema_50', 0):,.2f}\n"

            return ChatResponse(
                response=response_text,
                symbol=symbol,
                data=indicators,
                chart_update=True
            )

        elif intent == 'trading_strategy':
            # Use AI Orchestrator to build strategy
            print(f"[AI] Building strategy for {symbol}...")
            strategy = await orchestrator.build_strategy(
                symbol=symbol,
                timeframe=request.timeframe,
                user_prompt=message
            )

            response_text = f"**{symbol} Trading Strategy**\n\n"
            response_text += f"Current Price: ${current_price:,.2f}\n"
            response_text += f"📈 Strategy Type: {strategy.get('strategy_type', 'N/A')}\n"
            response_text += f"🎯 Market Bias: {strategy.get('market_bias', 'N/A')}\n"
            response_text += f"💪 Confidence: {strategy.get('confidence', 0):.1f}%\n\n"

            entry_conditions = strategy.get('entry_conditions', [])
            if entry_conditions:
                response_text += "✅ **Entry Conditions:**\n"
                for condition in entry_conditions[:3]:
                    response_text += f"• {condition}\n"
                response_text += "\n"

            risk = strategy.get('risk_management', {})
            if risk:
                response_text += "🛡️ **Risk Management:**\n"
                response_text += f"• Stop Loss: ${risk.get('stop_loss', 0):,.2f}\n"
                response_text += f"• Take Profit: ${risk.get('take_profit', 0):,.2f}\n"
                response_text += f"• Risk/Reward: {risk.get('risk_reward_ratio', 0):.2f}\n"

            return ChatResponse(
                response=response_text,
                symbol=symbol,
                data=strategy,
                chart_update=True
            )

        elif intent == 'current_price':
            response_text = f"**{symbol} Current Price**\n\n"
            response_text += f"💰 ${current_price:,.2f}\n\n"

            # Add recent price action
            recent_data = await OHLCRepository.get_ohlc_data(symbol, request.timeframe, limit=5)
            if len(recent_data) > 1:
                prev_close = float(recent_data[1]['close'])
                change = current_price - prev_close
                change_pct = (change / prev_close) * 100

                if change > 0:
                    response_text += f"📈 +${change:.2f} (+{change_pct:.2f}%)\n"
                else:
                    response_text += f"📉 ${change:.2f} ({change_pct:.2f}%)\n"

            return ChatResponse(
                response=response_text,
                symbol=symbol,
                data={'current_price': current_price},
                chart_update=True
            )

        else:
            # General query - use AI
            response_text = f"I can help you analyze **{symbol}**. You can ask me about:\n\n"
            response_text += "• Liquidity levels (support & resistance)\n"
            response_text += "• Technical indicators (RSI, MACD, EMA)\n"
            response_text += "• Trading strategies\n"
            response_text += "• Current price\n\n"
            response_text += "What would you like to know?"

            return ChatResponse(
                response=response_text,
                symbol=symbol,
                chart_update=True
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")


@router.get("/symbols")
async def get_available_symbols():
    """Get list of available cryptocurrency symbols"""
    symbols = [
        {"symbol": "BTCUSDT", "name": "Bitcoin", "exchange": "BINANCE"},
        {"symbol": "ETHUSDT", "name": "Ethereum", "exchange": "BINANCE"},
        {"symbol": "BNBUSDT", "name": "Binance Coin", "exchange": "BINANCE"},
        {"symbol": "SOLUSDT", "name": "Solana", "exchange": "BINANCE"},
        {"symbol": "XRPUSDT", "name": "Ripple", "exchange": "BINANCE"},
        {"symbol": "ADAUSDT", "name": "Cardano", "exchange": "BINANCE"},
        {"symbol": "DOGEUSDT", "name": "Dogecoin", "exchange": "BINANCE"},
        {"symbol": "DOTUSDT", "name": "Polkadot", "exchange": "BINANCE"},
        {"symbol": "AVAXUSDT", "name": "Avalanche", "exchange": "BINANCE"},
    ]

    return {"symbols": symbols}
