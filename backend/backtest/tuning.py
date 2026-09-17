"""
Search the exit plan and the rule's filter on seen data.

The tuner is handed the seen candles and nothing more - the boundary bar is
the last thing it can read, because a trade still open at the split closes at
that bar's open. Whatever it picks is then run once on unseen data by the
caller. That asymmetry is the whole point: a number chosen from two hundred
tries is worth much less than one measured on data nobody fitted to.

Signals depend on the rule's filter and exits on the plan, so each filter's
signals are derived from the cached tape once and reused across every exit
combination - which is what makes a grid of this size cost seconds.
"""
from dataclasses import dataclass
from itertools import product
from typing import Any, Callable, Dict, List, Optional, Sequence

from backtest.metrics import MIN_TRADES, period_metrics
from backtest.signals import distinct_setups, signals_from_tape
from backtest.trades import simulate
from models.backtest_schemas import ExitPlan, Grid

OBJECTIVE = "expectancy in R per trade on seen data"


@dataclass(frozen=True)
class Setting:
    filters: Dict[str, Any]
    stop_atr: float
    target_r: float
    max_bars: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "filters": dict(self.filters),
            "stop_atr": self.stop_atr,
            "target_r": self.target_r,
            "max_bars": self.max_bars,
        }


def filter_values(grid: Grid, agent: str) -> List[Dict[str, Any]]:
    if agent == "pattern":
        return [{"min_confidence": float(c)} for c in grid.min_confidence]
    if agent == "liquidity":
        return [{"min_strength": s} for s in grid.min_strength]
    return [{}]


def combinations(grid: Grid, agent: str) -> List[Setting]:
    return [
        Setting(filters, float(stop), float(target), int(bars))
        for filters, stop, target, bars in product(
            filter_values(grid, agent), grid.stop_atr, grid.target_r, grid.max_bars
        )
    ]


def plan_for(plan: ExitPlan, setting: Setting) -> ExitPlan:
    """The plan with this setting's exits. Costs and risk are never tuned."""
    return plan.model_copy(
        update={
            "stop_atr": setting.stop_atr,
            "stop_pct": None,
            "target_r": setting.target_r,
            "target_pct": None,
            "max_bars": setting.max_bars,
        }
    )


def tune(
    candles: Sequence[Dict[str, Any]],
    tape: List[list],
    params: Dict[str, Any],
    plan: ExitPlan,
    *,
    neutral: str,
    start: int,
    split: int,
    grid: Grid,
    timeframe_ms: int,
    persist_bars: int,
    cooldown_secs: int,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """
    Every setting measured on the seen slice. `candles` must be the seen
    candles plus the boundary bar - `candles[: split + 1]` - and never more.
    """
    settings = combinations(grid, params["agent"])
    signals_by_filter: Dict[str, List[Any]] = {}
    rows: List[Dict[str, Any]] = []

    for done, setting in enumerate(settings, start=1):
        key = repr(sorted(setting.filters.items()))
        if key not in signals_by_filter:
            filtered = {**params, **setting.filters}
            fires = signals_from_tape(
                tape, candles, filtered,
                timeframe_ms=timeframe_ms,
                persist_bars=persist_bars,
                cooldown_secs=cooldown_secs,
                start=start,
                end=split,
            )
            signals_by_filter[key] = distinct_setups(fires)

        sim = simulate(candles, signals_by_filter[key], start, split, plan_for(plan, setting), neutral)
        metrics = period_metrics(candles, sim, timeframe_ms)
        rows.append({
            "settings": setting.as_dict(),
            "trades": metrics["trades"],
            "expectancy_r": metrics["expectancy_r"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "total_return_pct": metrics["total_return_pct"],
        })
        if progress is not None:
            progress(done, len(settings))

    # Only settings with enough trades may win; among them the best expectancy,
    # and on a tie the one that hurt less on the way there.
    qualified = [r for r in rows if r["trades"] >= MIN_TRADES]
    pool = qualified or rows
    pool.sort(
        key=lambda r: (
            r["expectancy_r"] if r["expectancy_r"] is not None else float("-inf"),
            r["max_drawdown_pct"] if r["max_drawdown_pct"] is not None else float("-inf"),
        ),
        reverse=True,
    )
    if not qualified:
        pool.sort(key=lambda r: r["trades"], reverse=True)

    return {
        "tried": len(rows),
        "objective": OBJECTIVE,
        "min_trades": MIN_TRADES,
        "qualified": bool(qualified),
        "chosen": pool[0]["settings"],
        "top": pool[:5],
    }
