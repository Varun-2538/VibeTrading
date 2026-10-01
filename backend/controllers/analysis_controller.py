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

from analysis.patterns import (
    DEFAULT_SCALE,
    KINDS,
    MAX_PATTERNS,
    PRESETS,
    SCALES,
    SOURCES,
    detect_double_patterns,
)
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


class PatternRequest(WindowRequest):
    kinds: List[str] = list(KINDS)
    strictness: str = "balanced"
    source: str = "wick"
    scale: str = DEFAULT_SCALE
    max_results: int = Field(default=MAX_PATTERNS, ge=1, le=50)


@router.post("/analysis/patterns")
async def analyse_patterns(request: PatternRequest) -> Dict[str, Any]:
    """
    Double bottoms and tops among the candles in the window.

    Each pattern carries its state - forming, approaching or confirmed - so the
    chart can show a setup developing rather than only reporting completed
    ones.
    """
    try:
        candles = await CandleService.get_candles(
            request.symbol, request.timeframe, request.limit
        )
        visible = CandleService.window(candles, request.frm, request.to)
        # Detect everything, then show the top slice. Reporting both counts is
        # what makes the strictness control legible: on a long window the cap
        # can otherwise mask a real difference between the presets.
        all_found = detect_double_patterns(
            visible,
            strictness=request.strictness,
            kinds=tuple(request.kinds),
            source=request.source,
            scale=request.scale,
            max_results=None,
        )
        patterns = all_found[: request.max_results]
    except UnknownTimeframe as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        # Unknown strictness or pattern kind.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except CandleFetchError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    return {
        "symbol": request.symbol.upper(),
        "timeframe": request.timeframe,
        "strictness": request.strictness,
        "source": request.source,
        "scale": request.scale,
        "sample_size": len(visible),
        "total_found": len(all_found),
        "patterns": patterns,
    }


@router.get("/analysis/strictness")
async def list_strictness() -> Dict[str, List[str]]:
    """The strictness presets this deployment offers."""
    return {
        "strictness": list(PRESETS),
        "kinds": list(KINDS),
        "sources": list(SOURCES),
        "scales": list(SCALES),
    }


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
