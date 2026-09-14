from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# Enums
class TimeframeEnum(str, Enum):
    """Supported timeframes"""
    ONE_MIN = "1m"
    FIVE_MIN = "5m"
    FIFTEEN_MIN = "15m"
    THIRTY_MIN = "30m"
    ONE_HOUR = "1h"
    FOUR_HOUR = "4h"
    ONE_DAY = "1d"


class MarketBias(str, Enum):
    """Market bias types"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class StrategyType(str, Enum):
    """Strategy types"""
    SWING = "swing"
    SCALP = "scalp"
    DAY_TRADE = "day_trade"
    POSITION = "position"


# Request Models
class StrategyBuildRequest(BaseModel):
    """Request to build a trading strategy"""
    prompt: str = Field(..., description="User's natural language prompt")
    symbol: str = Field(..., description="Trading pair (e.g., BTC/USD)")
    timeframe: TimeframeEnum = Field(default=TimeframeEnum.ONE_HOUR)
    risk_tolerance: Optional[str] = Field(default="medium", description="low, medium, high")

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "Build a swing trading strategy for Bitcoin using RSI and liquidation zones",
                "symbol": "BTC/USD",
                "timeframe": "1h",
                "risk_tolerance": "medium"
            }
        }


class OHLCRequest(BaseModel):
    """Request for OHLC data"""
    symbol: str
    timeframe: TimeframeEnum = TimeframeEnum.ONE_HOUR
    limit: int = Field(default=240, ge=1, le=1000)


# Response Models
class OHLCData(BaseModel):
    """OHLC candle data"""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class LiquidationLevel(BaseModel):
    """Liquidation level data"""
    price: float
    strength: str  # weak, medium, strong
    type: str  # support or resistance
    reasoning: Optional[str] = None


class LiquidationZone(BaseModel):
    """Liquidation zone (range)"""
    start_price: float
    end_price: float
    strength: str
    label: str


class IndicatorAnalysis(BaseModel):
    """Technical indicator analysis"""
    rsi: Optional[float] = None
    rsi_signal: Optional[str] = None  # oversold, neutral, overbought
    macd: Optional[Dict[str, float]] = None
    macd_signal: Optional[str] = None  # bullish, bearish, neutral
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    trend: Optional[str] = None  # uptrend, downtrend, sideways


class LiquidationAnalysisResponse(BaseModel):
    """Response from Liquidation Agent"""
    support_levels: List[LiquidationLevel]
    resistance_levels: List[LiquidationLevel]
    liquidation_zones: List[LiquidationZone]
    analysis_summary: str
    timestamp: datetime


class IndicatorAnalysisResponse(BaseModel):
    """Response from Indicator Agent"""
    market_bias: MarketBias
    indicators: IndicatorAnalysis
    key_signals: List[str]
    confidence: str  # high, medium, low
    analysis_summary: str
    timestamp: datetime


class StrategyCondition(BaseModel):
    """Entry or exit condition"""
    description: str
    parameters: Dict[str, Any]


class RiskManagement(BaseModel):
    """Risk management parameters"""
    stop_loss: float
    take_profit: List[float]  # Multiple TP levels
    position_size_pct: float = Field(..., ge=0, le=100)
    risk_reward_ratio: float


class TradingStrategy(BaseModel):
    """Complete trading strategy"""
    strategy_id: Optional[str] = None
    symbol: str
    timeframe: str
    strategy_type: StrategyType
    entry_conditions: List[StrategyCondition]
    exit_conditions: List[StrategyCondition]
    risk_management: RiskManagement
    reasoning: str
    confidence_score: float = Field(..., ge=0, le=1)
    created_at: datetime


class StrategyBuildResponse(BaseModel):
    """Response for strategy build request"""
    success: bool
    strategy: TradingStrategy
    liquidation_analysis: LiquidationAnalysisResponse
    indicator_analysis: IndicatorAnalysisResponse
    execution_time_seconds: float
    timestamp: datetime


class ChartAnnotation(BaseModel):
    """Chart annotation data"""
    id: Optional[str] = None
    symbol: str
    type: str  # rectangle, line, arrow, text
    coordinates: Dict[str, Any]
    style: Dict[str, Any]
    label: str
    created_at: Optional[datetime] = None


class WebSocketMessage(BaseModel):
    """WebSocket message format"""
    type: str  # price_update, strategy_signal, annotation, status
    data: Dict[str, Any]
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Error response"""
    success: bool = False
    error: str
    details: Optional[str] = None
    timestamp: datetime
