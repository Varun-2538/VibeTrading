from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any
from datetime import datetime
from models.schemas import (
    StrategyBuildRequest,
    StrategyBuildResponse,
    TradingStrategy,
    LiquidationAnalysisResponse,
    IndicatorAnalysisResponse,
    ErrorResponse
)
from agents.orchestrator import OrchestratorAgent
from services.strategy_service import StrategyService

router = APIRouter(prefix="/api/strategy", tags=["Strategy"])

# Initialize orchestrator
orchestrator = OrchestratorAgent()


@router.post("/build", response_model=StrategyBuildResponse)
async def build_strategy(request: StrategyBuildRequest):
    """
    Build a trading strategy from user prompt

    This endpoint:
    1. Runs Liquidation Agent to detect support/resistance
    2. Runs Indicator Agent to analyze technical indicators
    3. Synthesizes findings into a complete trading strategy
    4. Creates chart annotations for liquidation zones

    Expected time: <60 seconds
    """
    try:
        # Check cache first
        cached_strategy = await StrategyService.get_cached_strategy(
            request.prompt,
            request.symbol
        )

        if cached_strategy:
            return StrategyBuildResponse(**cached_strategy)

        # Build strategy using orchestrator
        result = await orchestrator.build_strategy(
            user_prompt=request.prompt,
            symbol=request.symbol,
            timeframe=request.timeframe,
            risk_tolerance=request.risk_tolerance
        )

        # Parse strategy
        strategy_data = result['strategy']
        strategy = TradingStrategy(
            symbol=request.symbol,
            timeframe=request.timeframe,
            **strategy_data
        )

        # Parse liquidation analysis
        liq_data = result['liquidation_analysis']
        liquidation_analysis = LiquidationAnalysisResponse(
            support_levels=liq_data.get('support_levels', []),
            resistance_levels=liq_data.get('resistance_levels', []),
            liquidation_zones=liq_data.get('liquidation_zones', []),
            analysis_summary=liq_data.get('analysis_summary', ''),
            timestamp=liq_data.get('timestamp', datetime.utcnow())
        )

        # Parse indicator analysis
        ind_data = result['indicator_analysis']
        indicator_analysis = IndicatorAnalysisResponse(
            market_bias=ind_data.get('market_bias', 'neutral'),
            indicators=ind_data.get('indicators', {}),
            key_signals=ind_data.get('key_signals', []),
            confidence=ind_data.get('confidence', 'medium'),
            analysis_summary=ind_data.get('analysis_summary', ''),
            timestamp=ind_data.get('timestamp', datetime.utcnow())
        )

        response = StrategyBuildResponse(
            success=True,
            strategy=strategy,
            liquidation_analysis=liquidation_analysis,
            indicator_analysis=indicator_analysis,
            execution_time_seconds=result.get('execution_time_seconds', 0),
            timestamp=datetime.utcnow()
        )

        # Cache the response
        await StrategyService.cache_strategy(
            request.prompt,
            request.symbol,
            response.model_dump()
        )

        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Strategy building failed: {str(e)}"
        )


@router.get("/analyze/{symbol}")
async def quick_analysis(
    symbol: str,
    timeframe: str = "1h"
):
    """
    Quick market analysis without full strategy building

    Returns:
    - Market bias
    - Key support/resistance levels
    - Key trading signals
    """
    try:
        result = await orchestrator.quick_analysis(symbol, timeframe)
        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "strategy",
        "timestamp": datetime.utcnow()
    }
