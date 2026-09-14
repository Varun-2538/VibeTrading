from typing import Dict, Any, List
from datetime import datetime
import hashlib
import json
from services.market_data_service import MarketDataService
from services.cache_service import cache_service
from models.schemas import (
    TradingStrategy,
    StrategyType,
    StrategyCondition,
    RiskManagement
)


class StrategyService:
    """Service for trading strategy operations"""

    @staticmethod
    async def build_strategy(
        prompt: str,
        symbol: str,
        timeframe: str,
        liquidation_analysis: Dict[str, Any],
        indicator_analysis: Dict[str, Any]
    ) -> TradingStrategy:
        """
        Build a trading strategy from agent analyses

        Args:
            prompt: User's prompt
            symbol: Trading pair
            timeframe: Timeframe
            liquidation_analysis: Analysis from liquidation agent
            indicator_analysis: Analysis from indicator agent

        Returns:
            Complete trading strategy
        """
        # Determine strategy type from prompt
        strategy_type = StrategyService._determine_strategy_type(prompt)

        # Build entry conditions
        entry_conditions = StrategyService._build_entry_conditions(
            liquidation_analysis,
            indicator_analysis,
            strategy_type
        )

        # Build exit conditions
        exit_conditions = StrategyService._build_exit_conditions(
            liquidation_analysis,
            indicator_analysis,
            strategy_type
        )

        # Calculate risk management
        risk_management = StrategyService._calculate_risk_management(
            liquidation_analysis,
            indicator_analysis,
            strategy_type
        )

        # Generate reasoning
        reasoning = StrategyService._generate_reasoning(
            liquidation_analysis,
            indicator_analysis,
            entry_conditions,
            exit_conditions
        )

        # Calculate confidence score
        confidence_score = StrategyService._calculate_confidence(
            liquidation_analysis,
            indicator_analysis
        )

        strategy = TradingStrategy(
            symbol=symbol,
            timeframe=timeframe,
            strategy_type=strategy_type,
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions,
            risk_management=risk_management,
            reasoning=reasoning,
            confidence_score=confidence_score,
            created_at=datetime.utcnow()
        )

        return strategy

    @staticmethod
    def _determine_strategy_type(prompt: str) -> StrategyType:
        """Determine strategy type from user prompt"""
        prompt_lower = prompt.lower()

        if any(word in prompt_lower for word in ['swing', 'hold', 'days', 'week']):
            return StrategyType.SWING
        elif any(word in prompt_lower for word in ['scalp', 'quick', 'minutes', 'seconds']):
            return StrategyType.SCALP
        elif any(word in prompt_lower for word in ['day trade', 'intraday', 'daily']):
            return StrategyType.DAY_TRADE
        elif any(word in prompt_lower for word in ['position', 'long-term', 'months']):
            return StrategyType.POSITION
        else:
            return StrategyType.SWING  # Default

    @staticmethod
    def _build_entry_conditions(
        liquidation_analysis: Dict[str, Any],
        indicator_analysis: Dict[str, Any],
        strategy_type: StrategyType
    ) -> List[StrategyCondition]:
        """Build entry conditions based on analyses"""
        conditions = []

        market_bias = indicator_analysis.get('market_bias', 'neutral')
        indicators = indicator_analysis.get('indicators', {})
        support_levels = liquidation_analysis.get('support_levels', [])

        # Price-based entry (near support for long, resistance for short)
        if support_levels and market_bias == 'bullish':
            strongest_support = min(support_levels, key=lambda x: x.get('distance_pct', 100))
            conditions.append(StrategyCondition(
                description=f"Price near support level at ${strongest_support['price']:.2f}",
                parameters={
                    'type': 'price_level',
                    'level': strongest_support['price'],
                    'tolerance_pct': 1.0
                }
            ))

        # RSI-based entry
        rsi = indicators.get('rsi')
        if rsi:
            if market_bias == 'bullish' and rsi < 40:
                conditions.append(StrategyCondition(
                    description=f"RSI below 40 (currently {rsi:.2f}) - oversold signal",
                    parameters={
                        'type': 'rsi',
                        'threshold': 40,
                        'condition': 'below'
                    }
                ))
            elif market_bias == 'bearish' and rsi > 60:
                conditions.append(StrategyCondition(
                    description=f"RSI above 60 (currently {rsi:.2f}) - overbought signal",
                    parameters={
                        'type': 'rsi',
                        'threshold': 60,
                        'condition': 'above'
                    }
                ))

        # MACD-based entry
        macd_signal = indicators.get('macd_signal')
        if macd_signal == 'bullish' and market_bias == 'bullish':
            conditions.append(StrategyCondition(
                description="MACD bullish crossover confirmed",
                parameters={
                    'type': 'macd_crossover',
                    'direction': 'bullish'
                }
            ))
        elif macd_signal == 'bearish' and market_bias == 'bearish':
            conditions.append(StrategyCondition(
                description="MACD bearish crossover confirmed",
                parameters={
                    'type': 'macd_crossover',
                    'direction': 'bearish'
                }
            ))

        # Volume confirmation
        volume_ratio = indicators.get('volume_ratio', 1.0)
        if volume_ratio > 1.5:
            conditions.append(StrategyCondition(
                description=f"High volume confirmation ({volume_ratio:.1f}x average)",
                parameters={
                    'type': 'volume',
                    'min_ratio': 1.5
                }
            ))

        return conditions if conditions else [
            StrategyCondition(
                description="Manual entry based on market analysis",
                parameters={'type': 'manual'}
            )
        ]

    @staticmethod
    def _build_exit_conditions(
        liquidation_analysis: Dict[str, Any],
        indicator_analysis: Dict[str, Any],
        strategy_type: StrategyType
    ) -> List[StrategyCondition]:
        """Build exit conditions based on analyses"""
        conditions = []

        market_bias = indicator_analysis.get('market_bias', 'neutral')
        indicators = indicator_analysis.get('indicators', {})
        resistance_levels = liquidation_analysis.get('resistance_levels', [])

        # Price target based on resistance
        if resistance_levels and market_bias == 'bullish':
            strongest_resistance = min(resistance_levels, key=lambda x: x.get('distance_pct', 100))
            conditions.append(StrategyCondition(
                description=f"Take profit near resistance at ${strongest_resistance['price']:.2f}",
                parameters={
                    'type': 'price_target',
                    'target': strongest_resistance['price'],
                    'tolerance_pct': 0.5
                }
            ))

        # RSI exit
        rsi = indicators.get('rsi')
        if rsi:
            if market_bias == 'bullish':
                conditions.append(StrategyCondition(
                    description="Exit when RSI reaches overbought (>70)",
                    parameters={
                        'type': 'rsi',
                        'threshold': 70,
                        'condition': 'above'
                    }
                ))
            elif market_bias == 'bearish':
                conditions.append(StrategyCondition(
                    description="Exit when RSI reaches oversold (<30)",
                    parameters={
                        'type': 'rsi',
                        'threshold': 30,
                        'condition': 'below'
                    }
                ))

        # Trend reversal exit
        conditions.append(StrategyCondition(
            description="Exit on trend reversal signal (EMA crossover)",
            parameters={
                'type': 'ema_crossover',
                'ema_fast': 20,
                'ema_slow': 50
            }
        ))

        return conditions if conditions else [
            StrategyCondition(
                description="Manual exit based on market conditions",
                parameters={'type': 'manual'}
            )
        ]

    @staticmethod
    def _calculate_risk_management(
        liquidation_analysis: Dict[str, Any],
        indicator_analysis: Dict[str, Any],
        strategy_type: StrategyType
    ) -> RiskManagement:
        """Calculate risk management parameters"""
        current_price = liquidation_analysis.get('current_price', 0)
        support_levels = liquidation_analysis.get('support_levels', [])
        resistance_levels = liquidation_analysis.get('resistance_levels', [])

        # Determine stop loss (below nearest support)
        if support_levels:
            nearest_support = min(support_levels, key=lambda x: x.get('distance_pct', 100))
            stop_loss = nearest_support['price'] * 0.98  # 2% below support
        else:
            stop_loss = current_price * 0.95  # Default 5% stop loss

        # Determine take profit levels (at resistance levels)
        take_profit = []
        if resistance_levels:
            # Sort by distance
            sorted_resistance = sorted(resistance_levels, key=lambda x: x.get('distance_pct', 0))
            for i, level in enumerate(sorted_resistance[:3]):  # Max 3 TP levels
                take_profit.append(level['price'])

        if not take_profit:
            # Default TP levels based on R:R ratio
            risk = abs(current_price - stop_loss)
            take_profit = [
                current_price + (risk * 2),  # 2:1 R:R
                current_price + (risk * 3)   # 3:1 R:R
            ]

        # Position size based on strategy type
        position_size_map = {
            StrategyType.SCALP: 10.0,      # 10% for scalping
            StrategyType.DAY_TRADE: 15.0,  # 15% for day trading
            StrategyType.SWING: 20.0,      # 20% for swing trading
            StrategyType.POSITION: 25.0    # 25% for position trading
        }
        position_size_pct = position_size_map.get(strategy_type, 15.0)

        # Calculate R:R ratio
        avg_tp = sum(take_profit) / len(take_profit)
        risk = abs(current_price - stop_loss)
        reward = abs(avg_tp - current_price)
        risk_reward_ratio = reward / risk if risk > 0 else 2.0

        return RiskManagement(
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=position_size_pct,
            risk_reward_ratio=round(risk_reward_ratio, 2)
        )

    @staticmethod
    def _generate_reasoning(
        liquidation_analysis: Dict[str, Any],
        indicator_analysis: Dict[str, Any],
        entry_conditions: List[StrategyCondition],
        exit_conditions: List[StrategyCondition]
    ) -> str:
        """Generate strategy reasoning"""
        market_bias = indicator_analysis.get('market_bias', 'neutral')
        analysis_summary = indicator_analysis.get('analysis_summary', '')
        liq_summary = liquidation_analysis.get('analysis_summary', '')

        reasoning_parts = [
            f"Market Bias: {market_bias.upper()}",
            f"\nLiquidation Analysis: {liq_summary}",
            f"\nIndicator Analysis: {analysis_summary}",
            f"\nEntry Strategy: {'; '.join([c.description for c in entry_conditions])}",
            f"\nExit Strategy: {'; '.join([c.description for c in exit_conditions])}"
        ]

        return ' '.join(reasoning_parts)

    @staticmethod
    def _calculate_confidence(
        liquidation_analysis: Dict[str, Any],
        indicator_analysis: Dict[str, Any]
    ) -> float:
        """Calculate strategy confidence score (0-1)"""
        confidence = 0.5  # Base confidence

        # Increase confidence based on indicator alignment
        market_bias = indicator_analysis.get('market_bias', 'neutral')
        if market_bias in ['bullish', 'bearish']:
            confidence += 0.2

        # Check indicator signals
        indicators = indicator_analysis.get('indicators', {})
        rsi_signal = indicators.get('rsi_signal')
        macd_signal = indicators.get('macd_signal')

        if rsi_signal in ['oversold', 'overbought']:
            confidence += 0.1

        if macd_signal in ['bullish', 'bearish']:
            confidence += 0.1

        # Check liquidation levels
        support_levels = liquidation_analysis.get('support_levels', [])
        resistance_levels = liquidation_analysis.get('resistance_levels', [])

        if support_levels and resistance_levels:
            confidence += 0.1

        return min(confidence, 1.0)  # Cap at 1.0

    @staticmethod
    async def get_strategy_hash(prompt: str, symbol: str) -> str:
        """Generate hash for strategy caching"""
        content = f"{prompt}:{symbol}"
        return hashlib.md5(content.encode()).hexdigest()

    @staticmethod
    async def cache_strategy(
        prompt: str,
        symbol: str,
        strategy_data: Dict[str, Any]
    ) -> bool:
        """Cache a strategy"""
        prompt_hash = await StrategyService.get_strategy_hash(prompt, symbol)
        return await cache_service.cache_strategy(
            prompt_hash,
            symbol,
            strategy_data,
            expiration=7200  # 2 hours
        )

    @staticmethod
    async def get_cached_strategy(
        prompt: str,
        symbol: str
    ) -> Dict[str, Any]:
        """Get cached strategy"""
        prompt_hash = await StrategyService.get_strategy_hash(prompt, symbol)
        return await cache_service.get_cached_strategy(prompt_hash, symbol)
