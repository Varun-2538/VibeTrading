"""
What candle history exists for backtests.

Public: it describes market data, not anyone's rules. The UI reads it so it
never offers a backtest over history that is not there.
"""
from typing import Any, Dict

from fastapi import APIRouter

from repositories.history_repository import HistoryRepository
from services.cache_service import cache_service
from services.history_service import HISTORY_DEPTH_DAYS, missing_bars

router = APIRouter(prefix="/api/history", tags=["History"])

COVERAGE_CACHE_SECONDS = 60
CACHE_KEY = "history:coverage"


@router.get("/coverage")
async def get_coverage() -> Dict[str, Any]:
    cached = await cache_service.get(CACHE_KEY)
    if isinstance(cached, dict):
        return cached

    series = [
        {**s, "gaps": missing_bars(s["first"], s["last"], s["bars"], s["timeframe"])}
        for s in await HistoryRepository.coverage()
        if s["timeframe"] in HISTORY_DEPTH_DAYS
    ]
    body = {"depth_days": dict(HISTORY_DEPTH_DAYS), "series": series}
    await cache_service.set(CACHE_KEY, body, COVERAGE_CACHE_SECONDS)
    return body
