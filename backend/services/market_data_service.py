from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import numpy as np
from repositories.ohlc_repository import OHLCRepository
from services.cache_service import cache_service


class MarketDataService:
    """Service for market data operations and analysis"""

    @staticmethod
    async def get_ohlc_data(
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get OHLC data with caching

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            limit: Number of candles
            use_cache: Whether to use cache

        Returns:
            List of OHLC candles
        """
        # Try cache first
        if use_cache:
            cached_data = await cache_service.get_cached_ohlc_data(
                symbol, timeframe, limit
            )
            if cached_data:
                return cached_data

        # Fetch from database
        data = await OHLCRepository.get_ohlc_data(symbol, timeframe, limit)

        # Cache for 1 hour (3600 seconds)
        if use_cache and data:
            await cache_service.cache_ohlc_data(
                symbol, timeframe, limit, data, expiration=3600
            )

        return data

    @staticmethod
    async def get_latest_price(symbol: str, timeframe: str = "1h") -> Optional[float]:
        """
        Get latest price for a symbol

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe

        Returns:
            Latest close price or None
        """
        candle = await OHLCRepository.get_latest_candle(symbol, timeframe)
        return candle['close'] if candle else None

    @staticmethod
    async def calculate_technical_indicators(
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> Dict[str, Any]:
        """
        Calculate technical indicators from OHLC data

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            limit: Number of candles for calculation

        Returns:
            Dictionary of calculated indicators
        """
        ohlc_data = await MarketDataService.get_ohlc_data(
            symbol, timeframe, limit
        )

        if not ohlc_data:
            return {}

        closes = np.array([candle['close'] for candle in ohlc_data])
        highs = np.array([candle['high'] for candle in ohlc_data])
        lows = np.array([candle['low'] for candle in ohlc_data])
        volumes = np.array([candle['volume'] for candle in ohlc_data])

        indicators = {}

        # RSI (14 periods)
        rsi = MarketDataService._calculate_rsi(closes, period=14)
        indicators['rsi'] = float(rsi[-1]) if len(rsi) > 0 else None
        indicators['rsi_signal'] = MarketDataService._get_rsi_signal(rsi[-1]) if indicators['rsi'] else None

        # MACD
        macd_line, signal_line, histogram = MarketDataService._calculate_macd(closes)
        indicators['macd'] = {
            'macd_line': float(macd_line[-1]) if len(macd_line) > 0 else None,
            'signal_line': float(signal_line[-1]) if len(signal_line) > 0 else None,
            'histogram': float(histogram[-1]) if len(histogram) > 0 else None
        }
        indicators['macd_signal'] = MarketDataService._get_macd_signal(
            macd_line[-1], signal_line[-1]
        ) if indicators['macd']['macd_line'] else None

        # EMAs
        ema_20 = MarketDataService._calculate_ema(closes, period=20)
        ema_50 = MarketDataService._calculate_ema(closes, period=50)
        indicators['ema_20'] = float(ema_20[-1]) if len(ema_20) > 0 else None
        indicators['ema_50'] = float(ema_50[-1]) if len(ema_50) > 0 else None

        # Trend determination
        current_price = closes[-1]
        if indicators['ema_20'] and indicators['ema_50']:
            if current_price > indicators['ema_20'] > indicators['ema_50']:
                indicators['trend'] = 'uptrend'
            elif current_price < indicators['ema_20'] < indicators['ema_50']:
                indicators['trend'] = 'downtrend'
            else:
                indicators['trend'] = 'sideways'

        # Volume analysis
        avg_volume = np.mean(volumes[-20:])  # 20-period average
        current_volume = volumes[-1]
        indicators['volume_ratio'] = float(current_volume / avg_volume) if avg_volume > 0 else 1.0

        return indicators

    @staticmethod
    def _calculate_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
        """Calculate RSI indicator"""
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gains = np.zeros(len(prices))
        avg_losses = np.zeros(len(prices))

        avg_gains[period] = np.mean(gains[:period])
        avg_losses[period] = np.mean(losses[:period])

        for i in range(period + 1, len(prices)):
            avg_gains[i] = (avg_gains[i-1] * (period - 1) + gains[i-1]) / period
            avg_losses[i] = (avg_losses[i-1] * (period - 1) + losses[i-1]) / period

        rs = avg_gains / (avg_losses + 1e-10)  # Avoid division by zero
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def _get_rsi_signal(rsi_value: float) -> str:
        """Get RSI signal interpretation"""
        if rsi_value >= 70:
            return "overbought"
        elif rsi_value <= 30:
            return "oversold"
        else:
            return "neutral"

    @staticmethod
    def _calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
        """Calculate EMA indicator"""
        ema = np.zeros(len(prices))
        multiplier = 2 / (period + 1)

        # Start with SMA for first value
        ema[period - 1] = np.mean(prices[:period])

        for i in range(period, len(prices)):
            ema[i] = (prices[i] - ema[i-1]) * multiplier + ema[i-1]

        return ema

    @staticmethod
    def _calculate_macd(
        prices: np.ndarray,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> tuple:
        """Calculate MACD indicator"""
        ema_fast = MarketDataService._calculate_ema(prices, fast_period)
        ema_slow = MarketDataService._calculate_ema(prices, slow_period)

        macd_line = ema_fast - ema_slow
        signal_line = MarketDataService._calculate_ema(macd_line, signal_period)
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def _get_macd_signal(macd_line: float, signal_line: float) -> str:
        """Get MACD signal interpretation"""
        if macd_line > signal_line:
            return "bullish"
        elif macd_line < signal_line:
            return "bearish"
        else:
            return "neutral"

    @staticmethod
    async def detect_liquidation_levels(
        symbol: str,
        timeframe: str = "1h",
        lookback_periods: int = 240,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Detect liquidation levels (support/resistance) with smart caching

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            lookback_periods: Periods to analyze
            use_cache: Whether to use cache (default True, 5-min TTL)

        Returns:
            Dictionary with support and resistance levels
        """
        from services.cache_service import cache_service

        # Try cache first (5 minute TTL for live data)
        if use_cache:
            cached_levels = await cache_service.get_cached_liquidity_levels(symbol, timeframe)
            if cached_levels:
                print(f"[CACHE HIT] Liquidity levels for {symbol}")
                return cached_levels

        print(f"[CACHE MISS] Calculating fresh liquidity levels for {symbol}")

        # Get support and resistance levels
        levels = await OHLCRepository.calculate_support_resistance(
            symbol, timeframe, lookback_periods, sensitivity=0.02
        )

        # Get current price and convert to float
        current_price = await MarketDataService.get_latest_price(symbol, timeframe)
        current_price = float(current_price) if current_price else 0.0

        # Categorize levels by strength (based on proximity to current price)
        support_levels = []
        for price in levels.get('support', []):
            price_float = float(price)
            distance_pct = abs(current_price - price_float) / current_price * 100
            strength = "strong" if distance_pct < 2 else "medium" if distance_pct < 5 else "weak"
            support_levels.append({
                'price': price_float,
                'strength': strength,
                'distance_pct': round(distance_pct, 2)
            })

        resistance_levels = []
        for price in levels.get('resistance', []):
            price_float = float(price)
            distance_pct = abs(current_price - price_float) / current_price * 100
            strength = "strong" if distance_pct < 2 else "medium" if distance_pct < 5 else "weak"
            resistance_levels.append({
                'price': price_float,
                'strength': strength,
                'distance_pct': round(distance_pct, 2)
            })

        result = {
            'support_levels': support_levels,
            'resistance_levels': resistance_levels,
            'current_price': current_price
        }

        # Cache for 5 minutes (300 seconds) for live trading
        if use_cache:
            await cache_service.cache_liquidity_levels(symbol, timeframe, result, expiration=300)

        return result

    @staticmethod
    async def get_market_summary(
        symbol: str,
        timeframe: str = "1h"
    ) -> Dict[str, Any]:
        """
        Get comprehensive market summary

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe

        Returns:
            Market summary with price, indicators, and levels
        """
        # Fetch data in parallel
        current_price = await MarketDataService.get_latest_price(symbol, timeframe)
        indicators = await MarketDataService.calculate_technical_indicators(
            symbol, timeframe
        )
        liquidation_levels = await MarketDataService.detect_liquidation_levels(
            symbol, timeframe
        )

        return {
            'symbol': symbol,
            'timeframe': timeframe,
            'current_price': current_price,
            'indicators': indicators,
            'liquidation_levels': liquidation_levels,
            'timestamp': datetime.utcnow().isoformat()
        }

    @staticmethod
    async def calculate_indicators(
        symbol: str,
        timeframe: str = "1h",
        limit: int = 240
    ) -> Dict[str, Any]:
        """Alias for calculate_technical_indicators"""
        return await MarketDataService.calculate_technical_indicators(
            symbol, timeframe, limit
        )
