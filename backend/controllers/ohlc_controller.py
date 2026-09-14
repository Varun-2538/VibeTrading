from fastapi import APIRouter, HTTPException, Query, status
from typing import List, Dict, Any
from datetime import datetime
from models.schemas import OHLCData, ChartAnnotation
from services.market_data_service import MarketDataService
from repositories.annotation_repository import AnnotationRepository

router = APIRouter(prefix="/api", tags=["Market Data"])


@router.get("/ohlc/{symbol}", response_model=List[OHLCData])
async def get_ohlc_data(
    symbol: str,
    timeframe: str = Query("1h", description="Candle timeframe"),
    limit: int = Query(240, ge=1, le=1000, description="Number of candles")
):
    """
    Fetch OHLC (candlestick) data for a trading pair

    Args:
        symbol: Trading pair (e.g., BTC/USD)
        timeframe: Candle timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)
        limit: Number of candles to fetch (1-1000)

    Returns:
        List of OHLC candles in chronological order
    """
    try:
        data = await MarketDataService.get_ohlc_data(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            use_cache=True
        )

        if not data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No OHLC data found for {symbol}"
            )

        return data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch OHLC data: {str(e)}"
        )


@router.get("/price/{symbol}")
async def get_latest_price(
    symbol: str,
    timeframe: str = Query("1h", description="Candle timeframe")
):
    """
    Get latest price for a trading pair

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe

    Returns:
        Latest close price
    """
    try:
        price = await MarketDataService.get_latest_price(symbol, timeframe)

        if price is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No price data found for {symbol}"
            )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": price,
            "timestamp": datetime.utcnow()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch price: {str(e)}"
        )


@router.get("/indicators/{symbol}")
async def get_technical_indicators(
    symbol: str,
    timeframe: str = Query("1h", description="Candle timeframe"),
    limit: int = Query(240, description="Number of candles for calculation")
):
    """
    Calculate technical indicators (RSI, MACD, EMA) for a symbol

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        limit: Number of candles for calculation

    Returns:
        Calculated technical indicators
    """
    try:
        indicators = await MarketDataService.calculate_technical_indicators(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit
        )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "indicators": indicators,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate indicators: {str(e)}"
        )


@router.get("/liquidation-levels/{symbol}")
async def get_liquidation_levels(
    symbol: str,
    timeframe: str = Query("1h", description="Candle timeframe"),
    lookback_periods: int = Query(240, description="Periods to analyze")
):
    """
    Detect liquidation levels (support/resistance zones)

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        lookback_periods: Number of periods to analyze

    Returns:
        Support and resistance levels with strength indicators
    """
    try:
        levels = await MarketDataService.detect_liquidation_levels(
            symbol=symbol,
            timeframe=timeframe,
            lookback_periods=lookback_periods
        )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            **levels,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to detect liquidation levels: {str(e)}"
        )


@router.get("/market-summary/{symbol}")
async def get_market_summary(
    symbol: str,
    timeframe: str = Query("1h", description="Candle timeframe")
):
    """
    Get comprehensive market summary (price, indicators, levels)

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe

    Returns:
        Complete market summary
    """
    try:
        summary = await MarketDataService.get_market_summary(symbol, timeframe)
        return summary

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get market summary: {str(e)}"
        )


@router.get("/annotations/{symbol}")
async def get_annotations(
    symbol: str,
    limit: int = Query(100, ge=1, le=500, description="Max annotations to return")
):
    """
    Get chart annotations for a symbol

    Args:
        symbol: Trading pair
        limit: Maximum annotations to return

    Returns:
        List of chart annotations
    """
    try:
        annotations = await AnnotationRepository.get_annotations(symbol, limit)
        return {
            "symbol": symbol,
            "count": len(annotations),
            "annotations": annotations
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch annotations: {str(e)}"
        )


@router.delete("/annotations/{symbol}")
async def delete_annotations(symbol: str):
    """
    Delete all annotations for a symbol

    Args:
        symbol: Trading pair

    Returns:
        Number of annotations deleted
    """
    try:
        count = await AnnotationRepository.delete_annotations_by_symbol(symbol)
        return {
            "symbol": symbol,
            "deleted_count": count,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete annotations: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "market_data",
        "timestamp": datetime.utcnow()
    }
