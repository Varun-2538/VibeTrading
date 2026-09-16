"""
Backtests, owned by the signed-in wallet.

A backtest costs real CPU on a small machine, so it needs a session, and each
wallet may have one queued or running at a time. Ownership works as it does
for rules: another wallet's job id is a 404, never a 403.
"""
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from controllers.history_controller import get_coverage
from controllers.rules_controller import require_owner
from models.backtest_schemas import BacktestCreate, required_bars
from repositories.backtest_repository import BacktestRepository

router = APIRouter(prefix="/api/backtests", tags=["Backtests"])


def _iso(value):
    return value.isoformat() if value is not None else None


def serialize(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(job["id"]),
        "status": job["status"],
        "progress": float(job.get("progress") or 0),
        "created_at": _iso(job.get("created_at")),
        "started_at": _iso(job.get("started_at")),
        "finished_at": _iso(job.get("finished_at")),
        "request": job.get("request"),
        "report": job.get("report"),
        "error": job.get("error"),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_backtest(body: BacktestCreate, owner: str = Depends(require_owner)) -> Dict[str, Any]:
    if await BacktestRepository.count_active(owner):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You already have a backtest running. Wait for it to finish or cancel it.",
        )

    rule = body.rule
    symbol = rule.symbol.upper()
    needed = required_bars(rule.params.lookback)
    coverage = await get_coverage()
    have = next(
        (s["bars"] for s in coverage["series"] if s["symbol"] == symbol and s["timeframe"] == rule.timeframe),
        0,
    )
    if have < needed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{symbol} {rule.timeframe} has {have} bars of history; this rule needs {needed}.",
        )

    job = await BacktestRepository.create(owner, body.model_dump(mode="json"))
    return {"id": str(job["id"]), "status": job["status"]}


@router.get("")
async def list_backtests(owner: str = Depends(require_owner)) -> List[Dict[str, Any]]:
    return [serialize({**job, "report": None}) for job in await BacktestRepository.list_for_owner(owner)]


@router.get("/{job_id}")
async def get_backtest(job_id: UUID, owner: str = Depends(require_owner)) -> Dict[str, Any]:
    job = await BacktestRepository.get_for_owner(str(job_id), owner)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest not found")
    return serialize(job)


@router.delete("/{job_id}")
async def cancel_backtest(job_id: UUID, owner: str = Depends(require_owner)) -> Dict[str, str]:
    result = await BacktestRepository.cancel_or_delete(str(job_id), owner)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest not found")
    return {"result": result}
