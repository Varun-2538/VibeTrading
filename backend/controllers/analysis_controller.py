"""
Candles and viewport-scoped analysis.

Every analysis endpoint here takes the same {symbol, timeframe, from, to}
window so the chart can ask any question about exactly the candles it is
showing. Pattern and market-phase endpoints will be added alongside /levels
using this same request shape.
"""
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from services.candle_service import (
    CandleService,
    CandleFetchError,
    UnknownTimeframe,
)
from services.market_data_service import MarketDataService


router = APIRouter(prefix="/api", tags=["Analysis"])


class WindowRequest(BaseModel):
    symbol: str
    timeframe: str = "1h"
    # Unix milliseconds. Either bound may be omitted to leave that side open.
    frm: Optional[int] = Field(default=None, alias="from")
    to: Optional[int] = None
    limit: int = 1000

    class Config:
        populate_by_name = True


@router.get("/candles/{symbol}")
async def get_candles(
    symbol: str,
    timeframe: str = Query("1h", description="1m, 5m, 15m, 1h or 1d"),
    limit: int = Query(1000, ge=1, le=1000),
) -> List[Dict[str, Any]]:
    """
    Candles for a symbol, oldest first, with times in unix milliseconds.

    This is the chart's source of truth. Analysis endpoints read the same
    cached candles, so what is analysed is what is drawn.
    """
    try:
        return await CandleService.get_candles(symbol, timeframe, limit)
    except UnknownTimeframe as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except CandleFetchError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/timeframes")
async def list_timeframes() -> Dict[str, List[str]]:
    """The timeframes this deployment serves."""
    return {"timeframes": CandleService.timeframes()}


@router.post("/analysis/levels")
async def analyse_levels(request: WindowRequest) -> Dict[str, Any]:
    """
    Support and resistance computed only from the candles in the window.

    Zooming past the available data returns empty lists rather than an error,
    so the chart simply clears its overlay.
    """
    try:
        return await MarketDataService.detect_levels_in_window(
            symbol=request.symbol,
            timeframe=request.timeframe,
            frm=request.frm,
            to=request.to,
            limit=request.limit,
        )
    except UnknownTimeframe as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except CandleFetchError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
