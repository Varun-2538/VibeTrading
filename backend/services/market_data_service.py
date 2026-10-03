from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import numpy as np
from repositories.ohlc_repository import OHLCRepository
from services.cache_service import cache_service
from services.candle_service import CandleService
from analysis import indicators as indicator_math
from analysis.levels import detect_levels


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

        # Postgres NUMERIC arrives as Decimal; without an explicit dtype numpy
        # builds object arrays and the indicator math dies mixing Decimal with float.
        closes = np.array([candle['close'] for candle in ohlc_data], dtype=float)
        highs = np.array([candle['high'] for candle in ohlc_data], dtype=float)
        lows = np.array([candle['low'] for candle in ohlc_data], dtype=float)
        volumes = np.array([candle['volume'] for candle in ohlc_data], dtype=float)

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
        """
        RSI series. The arithmetic lives in analysis/indicators so the rule
        engine evaluates exactly what the chat reports. Warm-up bars come back
        as 0.0 here rather than NaN, which is what callers of this method have
        always been handed.
        """
        return np.nan_to_num(indicator_math.rsi(prices, period), nan=0.0)

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
        """EMA series; see _calculate_rsi for why this delegates."""
        return np.nan_to_num(indicator_math.ema(prices, period), nan=0.0)

    @staticmethod
    def _calculate_macd(
        prices: np.ndarray,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> tuple:
        """MACD line, signal line, histogram; see _calculate_rsi for why this delegates."""
        line, signal, hist = indicator_math.macd(prices, fast_period, slow_period, signal_period)
        return (
            np.nan_to_num(line, nan=0.0),
            np.nan_to_num(signal, nan=0.0),
            np.nan_to_num(hist, nan=0.0),
        )

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
        Detect liquidation levels (support/resistance) for a whole timeframe.

        Candles come from CandleService so the levels agree with whatever the
        chart is showing. For levels restricted to a visible window, use
        detect_levels_in_window instead.

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe (1m, 5m, 15m, 1h, 1d)
            lookback_periods: Candles to analyse
            use_cache: Whether to use the levels cache (5-min TTL)

        Returns:
            Dictionary with support and resistance levels
        """
        from services.cache_service import cache_service

        if use_cache:
            cached_levels = await cache_service.get_cached_liquidity_levels(symbol, timeframe)
            if cached_levels:
                print(f"[CACHE HIT] Liquidity levels for {symbol} {timeframe}")
                return cached_levels

        print(f"[CACHE MISS] Calculating fresh liquidity levels for {symbol} {timeframe}")

        candles = await CandleService.get_candles(symbol, timeframe, lookback_periods)
        result = detect_levels(candles)

        if use_cache:
            await cache_service.cache_liquidity_levels(symbol, timeframe, result, expiration=300)

        return result

    @staticmethod
    async def detect_levels_in_window(
        symbol: str,
        timeframe: str = "1h",
        frm: Optional[int] = None,
        to: Optional[int] = None,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        """
        Levels computed only from the candles inside a visible range.

        Not cached: the window changes with every pan, so a cache keyed on it
        would miss constantly while filling Redis with single-use entries. The
        underlying candles are cached by CandleService, which is where the cost
        actually is.
        """
        candles = await CandleService.get_candles(symbol, timeframe, limit)
        visible = CandleService.window(candles, frm, to)
        result = detect_levels(visible)
        result["timeframe"] = timeframe
        result["symbol"] = symbol.upper()
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
