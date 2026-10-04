"""
What trading the signals would have done to an account, one period at a time.

Each period starts from an equity of 1.0 so seen and unseen are compared on
equal terms. Expectancy is reported twice, before and after friction, so a
strategy that earns an edge and hands it to the pool can be told apart from one
that never had an edge. Drawdown and Sharpe read the mark-to-market equity at every
close, so a trade that went far against the account before recovering still
shows up in the drawdown.
"""
import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from backtest.signals import TapeSignal
from backtest.study import _r
from backtest.trades import Simulation, Trade, simulate
from models.backtest_schemas import ExitPlan

MIN_TRADES = 30
EQUITY_POINTS = 500
MAX_TRADES_LISTED = 500
YEAR_MS = 365 * 24 * 60 * 60 * 1000  # crypto trades every day


def _time(candles: Sequence[Dict[str, Any]], index: int) -> int:
    return int(candles[min(index, len(candles) - 1)]["time"])


def trade_row(candles: Sequence[Dict[str, Any]], trade: Trade) -> Dict[str, Any]:
    return {
        "entry_time": _time(candles, trade.entry_index),
        "entry": _r(trade.entry, 8),
        "exit_time": _time(candles, trade.exit_index),
        "exit": _r(trade.exit, 8),
        "direction": "long" if trade.direction == 1 else "short",
        "reason": trade.reason,
        "r": _r(trade.r, 3),
        "cost_r": _r(trade.cost_r, 3),
        "pct": _r(trade.ret * 100, 3),
        "bars": trade.bars_held,
    }


def max_drawdown_pct(equity: Sequence[float]) -> float:
    peak, worst = -math.inf, 0.0
    for value in equity:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst * 100


def longest_losing_streak(trades: Sequence[Trade]) -> int:
    best = run = 0
    for trade in trades:
        run = run + 1 if trade.r <= 0 else 0
        best = max(best, run)
    return best


def sharpe(equity: Sequence[float], timeframe_ms: int) -> Optional[float]:
    if len(equity) < 3:
        return None
    values = np.asarray(equity, dtype=float)
    returns = values[1:] / values[:-1] - 1
    spread = float(returns.std())
    if spread == 0:
        return None
    return float(returns.mean()) / spread * math.sqrt(YEAR_MS / timeframe_ms)


def downsample(candles: Sequence[Dict[str, Any]], lo: int, equity: Sequence[float]) -> List[List[float]]:
    if not equity:
        return []
    step = max(1, math.ceil(len(equity) / EQUITY_POINTS))
    picks = list(range(0, len(equity), step))
    if picks[-1] != len(equity) - 1:
        picks.append(len(equity) - 1)
    return [[int(candles[lo + k]["time"]), _r(equity[k], 5)] for k in picks]


def period_metrics(candles: Sequence[Dict[str, Any]], sim: Simulation, timeframe_ms: int) -> Dict[str, Any]:
    trades = sim.trades
    bars = sim.hi - sim.lo
    rs = [t.r for t in trades]
    costs = [t.cost_r for t in trades]
    pnl = [t.notional * t.ret for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_loss = -sum(p for p in pnl if p < 0)
    in_market = sum(t.bars_held for t in trades)
    listed = trades[-MAX_TRADES_LISTED:]
    first, last = float(candles[sim.lo]["close"]), float(candles[sim.hi - 1]["close"])

    return {
        "from": int(candles[sim.lo]["time"]),
        "to": int(candles[sim.hi - 1]["time"]),
        "bars": bars,
        "trades": len(trades),
        "win_rate": _r(len(wins) / len(trades)) if trades else None,
        "avg_win_r": _r(float(np.mean(wins)), 3) if wins else None,
        "avg_loss_r": _r(float(np.mean(losses)), 3) if losses else None,
        "expectancy_r": _r(float(np.mean(rs)), 3) if rs else None,
        # What the strategy earned before friction, and what friction took. A
        # negative expectancy with a healthy gross number is a cost problem,
        # not a signal problem - a different thing to fix.
        "gross_expectancy_r": _r(float(np.mean(rs)) + float(np.mean(costs)), 3) if rs else None,
        "cost_r": _r(float(np.mean(costs)), 3) if costs else None,
        "profit_factor": _r(sum(p for p in pnl if p > 0) / gross_loss, 3) if gross_loss > 0 else None,
        "total_return_pct": _r((sim.equity[-1] - 1) * 100, 3) if sim.equity else None,
        "max_drawdown_pct": _r(max_drawdown_pct(sim.equity), 3) if sim.equity else None,
        "sharpe": _r(sharpe(sim.equity, timeframe_ms), 3),
        "exposure_pct": _r(min(in_market, bars) / bars * 100, 2) if bars else None,
        "longest_losing_streak": longest_losing_streak(trades),
        "buy_hold_pct": _r((last / first - 1) * 100, 3) if first else None,
        "skipped_in_position": sim.skipped_in_position,
        "skipped_neutral": sim.skipped_neutral,
        "skipped_no_room": sim.skipped_no_room,
        "equity": downsample(candles, sim.lo, sim.equity),
        "trade_list": [trade_row(candles, t) for t in listed],
        "trades_listed": len(listed),
        "flags": ["too_few_trades"] if len(trades) < MIN_TRADES else [],
    }


def trade_period(
    candles: Sequence[Dict[str, Any]],
    signals: Sequence[TapeSignal],
    lo: int,
    hi: int,
    plan: ExitPlan,
    neutral: str,
    timeframe_ms: int,
) -> Dict[str, Any]:
    return period_metrics(candles, simulate(candles, signals, lo, hi, plan, neutral), timeframe_ms)
