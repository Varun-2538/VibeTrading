"""
Signals into trades, with fills that err against the strategy.

One position at a time. Entry at the next bar's open. Exits, first hit wins:
the stop, the target, the bar limit, an opposite signal (optional), or the end
of the period. Where a bar's range cannot say which came first, the worse
outcome is assumed: a bar touching both stop and target is a stop. A bar that
opens beyond the stop fills at that open, not at the stop - and one that opens
beyond the target fills at the better open, because honesty runs both ways.
Every fill pays price impact, and every swap pays its pool fee and its gas.

What the friction cost is kept per trade, in R, because that is the number
that decides whether a real edge survives: a 1.5-ATR stop on an hourly major
is around 0.6% of price, so a 0.3% round trip is half of what the strategy has
to earn before it keeps anything.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backtest.signals import TapeSignal
from models.backtest_schemas import ExitPlan
from services.trade_plan import (
    bar_exit,
    bracket,
    exit_price,
    frictionless_return,
    in_r,
    signed_direction,
    time_exit_bar_index,
    tradable,
    trade_return,
)


@dataclass(frozen=True)
class Trade:
    signal_index: int
    direction: int
    entry_index: int
    entry: float
    stop: float
    target: Optional[float]
    exit_index: int
    exit: float
    reason: str
    notional: float
    ret: float
    r: float
    cost_r: float
    equity_after: float

    @property
    def gross_r(self) -> float:
        """What the trade would have made with no fees, gas or price impact."""
        return self.r + self.cost_r

    @property
    def bars_held(self) -> int:
        intrabar = 1 if self.reason in ("stop", "target") else 0
        return max(1, self.exit_index - self.entry_index + intrabar)


@dataclass
class Simulation:
    lo: int
    hi: int
    trades: List[Trade] = field(default_factory=list)
    equity: List[float] = field(default_factory=list)
    skipped_in_position: int = 0
    skipped_neutral: int = 0
    skipped_no_room: int = 0
    # Signals in a direction this venue cannot take. Counted apart from
    # skipped_neutral, because "no direction of its own" and "a short on a spot
    # pool" are different reasons and only one of them is about the venue.
    skipped_side: int = 0


def _exit(opens, highs, lows, closes, n, entry_i, hi, d, stop, target, max_bars, opposite_at) -> Tuple[int, float, str]:
    """
    Walk the bars after entry until something ends the trade.

    What each bar does is trade_plan.bar_exit - shared with the live monitor, so
    the stop and the target mean one thing. What is left here is what genuinely
    needs the whole array: the search for an opposing signal, the bar limit, and
    the end of the period.
    """
    def boundary() -> Tuple[int, float, str]:
        if hi < n:
            return hi, opens[hi], "end"
        return hi - 1, closes[hi - 1], "end"

    def next_open(j: int, reason: str) -> Tuple[int, float, str]:
        return (j, opens[j], reason) if j < hi else boundary()

    time_at = time_exit_bar_index(entry_i, max_bars)
    for j in range(entry_i, hi):
        hit = bar_exit(opens[j], highs[j], lows[j], d, stop, target, first_bar=j == entry_i)
        if hit is not None:
            price, reason = hit
            return j, price, reason
        if opposite_at is not None and j == opposite_at:
            return next_open(j + 1, "opposite")
        if j >= time_at - 1:
            return next_open(j + 1, "time")
    return boundary()


def _equity_path(trades: List[Trade], closes: Sequence[float], lo: int, hi: int) -> List[float]:
    path: List[float] = []
    closed, t = 1.0, 0
    for j in range(lo, hi):
        while t < len(trades) and trades[t].exit_index <= j:
            closed = trades[t].equity_after
            t += 1
        current = trades[t] if t < len(trades) and trades[t].entry_index <= j else None
        if current is None:
            path.append(closed)
        else:
            move = current.direction * (closes[j] - current.entry) / current.entry
            path.append(closed * (1 + current.notional * move))
    if trades and trades[-1].exit_index >= hi and path:
        path[-1] = trades[-1].equity_after
    return path


def simulate(
    candles: Sequence[Dict[str, Any]],
    signals: Sequence[TapeSignal],
    lo: int,
    hi: int,
    plan: ExitPlan,
    neutral: str,
    sides: str = "both",
) -> Simulation:
    n = len(candles)
    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    sim = Simulation(lo, hi)
    # Mapped without the side filter, so an opposing signal this venue cannot
    # trade can still close a position - on a long-only pool a bearish signal
    # means "get out", which is exactly what exit_on_opposite is for.
    directed = [(s.index, signed_direction(s.direction, neutral)) for s in signals if lo <= s.index < hi]
    equity = 1.0
    busy_until = -1  # the bar the last trade exited on

    for k, (i, d) in enumerate(directed):
        if d is None:
            sim.skipped_neutral += 1
            continue
        if not tradable(d, sides):
            sim.skipped_side += 1
            continue
        if i < busy_until:
            sim.skipped_in_position += 1
            continue
        entry_i = i + 1
        if entry_i >= hi:
            sim.skipped_no_room += 1
            continue

        plan_for_trade = bracket(plan, candles, i, opens[entry_i], d)
        if plan_for_trade is None:
            sim.skipped_no_room += 1
            continue
        entry, dist = plan_for_trade.entry, plan_for_trade.dist
        stop, target = plan_for_trade.stop, plan_for_trade.target

        opposite_at = None
        if plan.exit_on_opposite:
            opposite_at = next((j for j, dj in directed[k + 1:] if dj == -d and j >= entry_i), None)

        exit_i, raw, reason = _exit(opens, highs, lows, closes, n, entry_i, hi, d, stop, target, plan.max_bars, opposite_at)
        fill = exit_price(raw, d, plan.slippage_pct)
        ret = trade_return(entry, fill, d, plan.swap_cost_pct)
        # The same trade with no friction at all: in and out at the untouched
        # prices. The difference is what the pool, the gas and the impact took.
        cost = frictionless_return(opens[entry_i], raw, d) - ret
        notional = plan_for_trade.notional
        equity *= 1 + notional * ret
        sim.trades.append(Trade(i, d, entry_i, entry, stop, target, exit_i, fill, reason, notional, ret,
                                in_r(ret, entry, dist), in_r(cost, entry, dist), equity))
        busy_until = exit_i

    sim.equity = _equity_path(sim.trades, closes, lo, hi)
    return sim
