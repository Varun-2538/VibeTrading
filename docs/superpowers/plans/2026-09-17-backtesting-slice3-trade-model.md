# Backtesting Slice 3: Trade Model and Metrics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every backtest report also says what *trading* the signal would have done — per period, with stops, targets, fees and slippage: win rate, expectancy in R, profit factor, return, drawdown, Sharpe, an equity curve across the seen | unseen boundary, and a trade list whose recent trades can be drawn on the chart.

**Architecture:** Two pure modules turn the distinct setups slice 2 already computes into trades (`backtest/trades.py`, conservative fills) and into metrics (`backtest/metrics.py`). The runner adds a `trades` section to the report; the request gains an `exit` plan with defaults, so existing clients keep working. In the browser, the sheet grows exit-plan inputs and the trade report; marking trades dispatches a window event the page turns into chart marks tied to their pair and timeframe.

**Tech Stack:** Python 3.11, numpy, pytest; Next.js 15, React 19, lightweight-charts 5.2, shadcn/ui, vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-backtesting-design.md` — "4. Trade model", "5. Metrics", "UI", "Slices → 3". Slice 2 is live: `TapeSignal`, `distinct_setups`, `signed`, `ATR_BARS`, `_r`, `run_job`, `BacktestCreate`, `lib/backtests.ts`, `components/backtest-sheet.tsx`.

## Global Constraints

- Fills (spec, verbatim intent): entry at the open of bar `i+1` with slippage against the trade; a bar touching both stop and target is a **stop**; a bar opening beyond the stop fills at its **open**; a bar opening beyond the target fills at its open; bar-limit and opposite-signal exits fill at the **next bar's open**; fees `fee_pct` per side on notional.
- Defaults: `stop_atr 1.5`, `target_r 2`, `max_bars 20`, `exit_on_opposite false`, `fee_pct 0.1`, `slippage_pct 0.02`, `risk_pct 1`.
- Sizing: risk `risk_pct` of equity at the stop; notional capped at 100% of equity (no leverage); compounded.
- A trade still open at a period's end closes at the **open of the first bar after the period** (the boundary bar), or at the last close when the period ends the history.
- `MIN_TRADES = 30` → flag `too_few_trades`. Equity curve ≤ 500 points per period; trade list ≤ 500 most recent trades per period.
- Chart marks only for trades whose entry lies inside the chart's loaded window (`CHART_BARS = 1000`, with a 10-bar margin); markers whose bar is not loaded are never drawn.
- JSON: no NaN/Infinity (use `_r`). Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

**Running tests.** Backend from `backend/` with the Python 3.11 env: `python -m pytest -q` (baseline **395**). Frontend from `frontend/`: `npx vitest run` (baseline **56**), `npx tsc --noEmit -p .` (only the pre-existing `tests/sw.test.ts` error), `npx next build`.

## Decisions this plan makes

Record in the spec in Task 8.

1. **Trades come from distinct setups**, like the study: a setup is traded once, not re-entered on every bar its alert repeats.
2. A signal on the bar before a trade's open-price exit is skipped (the position is still held at that close).
3. When a stop cannot be sized (ATR not yet available, or zero), the signal is counted in `skipped_no_room` with late signals that have no bar left to enter on.
4. **Equity is marked to market at each close**, so drawdown includes open-trade losses.
5. The equity chart draws unseen continuing from seen's final equity; each period's metrics still start from 1.0.

## File Structure

| File | Responsibility |
|---|---|
| Modify `backend/models/backtest_schemas.py` | `ExitPlan`; `BacktestCreate.exit`. |
| Create `backend/backtest/trades.py` | `Trade`, `Simulation`, `simulate`. |
| Create `backend/backtest/metrics.py` | `period_metrics`, `trade_period`, helpers. |
| Modify `backend/backtest/runner.py` | `trades` section and `meta.exit`. |
| Create `backend/tests/test_backtest_trades.py`; modify `test_backtest_schemas.py`, `test_backtest_runner.py` | Tests. |
| Modify `frontend/lib/backtests.ts`, `frontend/tests/backtests.test.ts` | Types, helpers, event. |
| Modify `frontend/components/mark-overlay.tsx`, `frontend/components/price-chart.tsx`, `frontend/app/app/page.tsx` | Draw only loaded bars; page-owned trade marks. |
| Replace `frontend/components/backtest-sheet.tsx` | Exit inputs, trade report. |

---

### Task 1: The exit plan

**Files:** Modify `backend/models/backtest_schemas.py`; Test `backend/tests/test_backtest_schemas.py` (append)

**Interfaces:** Produces `class ExitPlan(BaseModel)` with the fields and defaults above and a validator requiring `stop_atr` or `stop_pct`; `BacktestCreate.exit: ExitPlan` (default `ExitPlan()`). When `stop_pct` is set it wins over `stop_atr`; when `target_pct` is set it wins over `target_r`; both targets `None` means exits by stop, bar limit, opposite signal or period end only.

- [ ] **Step 1: Failing test** (append)

```python
def test_exit_plan_defaults_and_needs_a_stop():
    body = BacktestCreate(rule=RULE)
    assert (body.exit.stop_atr, body.exit.target_r, body.exit.max_bars, body.exit.fee_pct) == (1.5, 2.0, 20, 0.1)
    assert (body.exit.slippage_pct, body.exit.risk_pct, body.exit.exit_on_opposite) == (0.02, 1.0, False)
    with pytest.raises(ValidationError, match="needs a stop"):
        BacktestCreate(rule=RULE, exit={"stop_atr": None})
```

- [ ] **Step 2:** Run `python -m pytest tests/test_backtest_schemas.py -q` → FAIL (`AttributeError: 'BacktestCreate' object has no attribute 'exit'`).

- [ ] **Step 3: Implement.** In `backend/models/backtest_schemas.py` change `from typing import Literal, Tuple` to `from typing import Literal, Optional, Tuple`, and insert above `class BacktestCreate`:

```python
class ExitPlan(BaseModel):
    """
    How a signal becomes a trade and how the trade ends. The defaults are a
    starting point for the report, not advice.
    """

    stop_atr: Optional[float] = Field(default=1.5, gt=0, le=20)
    stop_pct: Optional[float] = Field(default=None, gt=0, le=50)
    target_r: Optional[float] = Field(default=2.0, gt=0, le=20)
    target_pct: Optional[float] = Field(default=None, gt=0, le=200)
    max_bars: int = Field(default=20, ge=1, le=500)
    exit_on_opposite: bool = False
    fee_pct: float = Field(default=0.1, ge=0, le=1)
    slippage_pct: float = Field(default=0.02, ge=0, le=1)
    risk_pct: float = Field(default=1.0, gt=0, le=10)

    @model_validator(mode="after")
    def _has_a_stop(self) -> "ExitPlan":
        if self.stop_atr is None and self.stop_pct is None:
            raise ValueError("An exit plan needs a stop: stop_atr or stop_pct")
        return self
```

and add to `BacktestCreate`, after `split`:

```python
    exit: ExitPlan = Field(default_factory=ExitPlan)
```

- [ ] **Step 4:** Run → 7 passed.
- [ ] **Step 5: Commit** `git add backend/models/backtest_schemas.py backend/tests/test_backtest_schemas.py && git commit -m "Exit plan for backtest trades" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 2: Signals into trades

**Files:** Create `backend/backtest/trades.py`; Test `backend/tests/test_backtest_trades.py`

**Interfaces:**
- Consumes: `TapeSignal`, `signed`, `ATR_BARS`, `atr`, `ExitPlan`.
- Produces: `@dataclass(frozen=True) Trade(signal_index, direction: int, entry_index, entry, stop, target: Optional[float], exit_index, exit, reason: str, notional, ret, r, equity_after)` with property `bars_held`; `@dataclass Simulation(lo, hi, trades, equity, skipped_in_position, skipped_neutral, skipped_no_room)`; `simulate(candles, signals, lo, hi, plan, neutral) -> Simulation`. `reason ∈ {stop, target, time, opposite, end}`; `ret` is the return on notional after costs; `r = ret × entry / stop distance`; `equity` has one mark-to-market value per bar in `[lo, hi)`.

- [ ] **Step 1: Failing tests** — `backend/tests/test_backtest_trades.py`:

```python
"""Fills that err against the strategy, and the account they add up to."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.signals import TapeSignal
from backtest.trades import simulate
from models.backtest_schemas import ExitPlan
from walks import H, T0

FREE = dict(fee_pct=0, slippage_pct=0)
FLAT = (100, 100.5, 99.5, 100)


def bars(*ohlc):
    return [{"time": T0 + i * H, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
            for i, (o, h, l, c) in enumerate(ohlc)]


def sig(i, direction="bullish"):
    return TapeSignal(i, T0 + i * H, f"s{i}", direction, False)


def plan(**kw):
    base = dict(stop_pct=2, target_pct=4, max_bars=50, **FREE)
    base.update(kw)
    return ExitPlan(**base)


def one(candles, signals, p, hi=None, neutral="skip"):
    return simulate(candles, signals, 0, hi or len(candles), p, neutral)


def test_a_bar_touching_stop_and_target_is_a_stop():
    t = one(bars(FLAT, (100, 105, 97, 101), FLAT), [sig(0)], plan()).trades[0]
    assert (t.entry_index, t.exit_index, t.reason, t.exit) == (1, 1, "stop", 98.0)
    assert t.r == pytest.approx(-1.0)


def test_gap_through_the_stop_fills_at_the_open():
    t = one(bars(FLAT, (100, 101, 99, 100), (95, 96, 94, 95), FLAT), [sig(0)], plan()).trades[0]
    assert (t.exit_index, t.reason, t.exit) == (2, "stop", 95.0)
    assert t.r == pytest.approx(-2.5)


def test_gap_through_the_target_fills_at_the_better_open():
    t = one(bars(FLAT, (100, 101, 99, 100), (106, 107, 105, 106), FLAT), [sig(0)], plan()).trades[0]
    assert (t.reason, t.exit) == ("target", 106.0) and t.r == pytest.approx(3.0)


def test_bar_limit_exits_at_the_next_open():
    t = one(bars(FLAT, FLAT, FLAT, (101, 101.5, 100.5, 101), FLAT), [sig(0)], plan(max_bars=2)).trades[0]
    assert (t.exit_index, t.reason, t.exit) == (3, "time", 101.0)


def test_an_opposite_signal_exits_at_the_next_open_and_is_not_traded():
    sim = one(bars(FLAT, FLAT, FLAT, FLAT, FLAT), [sig(0), sig(1, "bearish")], plan(exit_on_opposite=True))
    assert [(t.exit_index, t.reason) for t in sim.trades] == [(2, "opposite")]
    assert sim.skipped_in_position == 1


def test_a_trade_open_at_the_split_closes_at_the_boundary_open():
    candles = bars(FLAT, FLAT, FLAT, (102, 102.5, 101.5, 102), FLAT)
    t = one(candles, [sig(0)], plan(), hi=3).trades[0]
    assert (t.exit_index, t.reason, t.exit) == (3, "end", 102.0)


def test_short_trades_mirror_long_ones():
    t = one(bars(FLAT, (100, 103, 99, 101), FLAT), [sig(0, "bearish")], plan()).trades[0]
    assert (t.direction, t.stop, t.reason, t.exit) == (-1, 102.0, "stop", 102.0)


def test_costs_are_paid_on_both_sides():
    t = one(bars(FLAT, (100, 105, 99, 104), FLAT), [sig(0)], plan(fee_pct=0.1, slippage_pct=0.1)).trades[0]
    entry = 100 * 1.001
    fill = entry * 1.04 * 0.999
    assert t.entry == pytest.approx(entry) and t.exit == pytest.approx(fill)
    assert t.ret == pytest.approx((fill - entry) / entry - 0.001 * (1 + fill / entry))


def test_risk_sizes_the_position_and_never_levers():
    wide = one(bars(FLAT, (100, 105, 99, 104), FLAT), [sig(0)], plan(stop_pct=2)).trades[0]
    tight = one(bars(FLAT, (100, 105, 99, 104), FLAT), [sig(0)], plan(stop_pct=0.5)).trades[0]
    assert wide.notional == pytest.approx(0.5) and tight.notional == pytest.approx(1.0)


def test_atr_stop_uses_the_range_at_the_signal_bar():
    flat = [(100, 101, 99, 100)] * 20
    t = one(bars(*flat), [sig(16)], ExitPlan(stop_atr=1.5, target_r=None, max_bars=2, **FREE)).trades[0]
    assert t.stop == pytest.approx(97.0) and t.target is None


def test_neutral_signals_follow_the_choice_and_late_signals_have_no_room():
    candles = bars(FLAT, (100, 105, 99, 104), FLAT)
    assert one(candles, [sig(0, "neutral")], plan()).skipped_neutral == 1
    assert len(one(candles, [sig(0, "neutral")], plan(), neutral="long").trades) == 1
    assert one(candles, [sig(2)], plan()).skipped_no_room == 1


def test_one_position_at_a_time():
    sim = one(bars(*[FLAT] * 6), [sig(0), sig(1), sig(3)], plan(max_bars=2))
    assert [t.entry_index for t in sim.trades] == [1, 4] and sim.skipped_in_position == 1
```

- [ ] **Step 2:** Run `python -m pytest tests/test_backtest_trades.py -q` → FAIL (`No module named 'backtest.trades'`).

- [ ] **Step 3: Implement** `backend/backtest/trades.py`:

```python
"""
Signals into trades, with fills that err against the strategy.

One position at a time. Entry at the next bar's open. Exits, first hit wins:
the stop, the target, the bar limit, an opposite signal (optional), or the end
of the period. Where a bar's range cannot say which came first, the worse
outcome is assumed: a bar touching both stop and target is a stop. A bar that
opens beyond the stop fills at that open, not at the stop - and one that opens
beyond the target fills at the better open, because honesty runs both ways.
Every fill pays slippage, every side pays fees.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from analysis.patterns import atr
from backtest.signals import TapeSignal
from backtest.study import ATR_BARS, signed
from models.backtest_schemas import ExitPlan


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
    equity_after: float

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


def _exit(opens, highs, lows, closes, n, entry_i, hi, d, stop, target, max_bars, opposite_at) -> Tuple[int, float, str]:
    def boundary() -> Tuple[int, float, str]:
        if hi < n:
            return hi, opens[hi], "end"
        return hi - 1, closes[hi - 1], "end"

    def next_open(j: int, reason: str) -> Tuple[int, float, str]:
        return (j, opens[j], reason) if j < hi else boundary()

    for j in range(entry_i, hi):
        if j > entry_i:
            o = opens[j]
            if (d == 1 and o <= stop) or (d == -1 and o >= stop):
                return j, o, "stop"
            if target is not None and ((d == 1 and o >= target) or (d == -1 and o <= target)):
                return j, o, "target"
        if (d == 1 and lows[j] <= stop) or (d == -1 and highs[j] >= stop):
            return j, stop, "stop"
        if target is not None and ((d == 1 and highs[j] >= target) or (d == -1 and lows[j] <= target)):
            return j, target, "target"
        if opposite_at is not None and j == opposite_at:
            return next_open(j + 1, "opposite")
        if j - entry_i + 1 >= max_bars:
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
) -> Simulation:
    n = len(candles)
    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    slip, fee, risk = plan.slippage_pct / 100, plan.fee_pct / 100, plan.risk_pct / 100

    sim = Simulation(lo, hi)
    directed = [(s.index, signed(s.direction, neutral)) for s in signals if lo <= s.index < hi]
    equity = 1.0
    busy_until = -1  # the bar the last trade exited on

    for k, (i, d) in enumerate(directed):
        if d is None:
            sim.skipped_neutral += 1
            continue
        if i < busy_until:
            sim.skipped_in_position += 1
            continue
        entry_i = i + 1
        if entry_i >= hi:
            sim.skipped_no_room += 1
            continue

        entry = opens[entry_i] * (1 + d * slip)
        if plan.stop_pct is not None:
            dist = entry * plan.stop_pct / 100
        else:
            unit = atr(candles[i + 1 - ATR_BARS: i + 1]) if i + 1 >= ATR_BARS else 0.0
            dist = plan.stop_atr * unit
        if dist <= 0:
            sim.skipped_no_room += 1
            continue

        stop = entry - d * dist
        if plan.target_pct is not None:
            target: Optional[float] = entry + d * entry * plan.target_pct / 100
        elif plan.target_r is not None:
            target = entry + d * plan.target_r * dist
        else:
            target = None

        opposite_at = None
        if plan.exit_on_opposite:
            opposite_at = next((j for j, dj in directed[k + 1:] if dj == -d and j >= entry_i), None)

        exit_i, raw, reason = _exit(opens, highs, lows, closes, n, entry_i, hi, d, stop, target, plan.max_bars, opposite_at)
        fill = raw * (1 - d * slip)
        ret = d * (fill - entry) / entry - fee * (1 + fill / entry)
        notional = min(1.0, risk / (dist / entry))
        equity *= 1 + notional * ret
        sim.trades.append(Trade(i, d, entry_i, entry, stop, target, exit_i, fill, reason, notional, ret, ret * entry / dist, equity))
        busy_until = exit_i

    sim.equity = _equity_path(sim.trades, closes, lo, hi)
    return sim
```

- [ ] **Step 4:** Run → 12 passed.
- [ ] **Step 5: Commit** `git add backend/backtest/trades.py backend/tests/test_backtest_trades.py && git commit -m "Turn signals into trades with conservative fills" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 3: Metrics

**Files:** Create `backend/backtest/metrics.py`; Test `backend/tests/test_backtest_trades.py` (append)

**Interfaces:** Produces `MIN_TRADES`, `EQUITY_POINTS`, `MAX_TRADES_LISTED`, `max_drawdown_pct(equity) -> float` (≤ 0), `longest_losing_streak(trades) -> int`, `sharpe(equity, timeframe_ms) -> Optional[float]`, `downsample(candles, lo, equity) -> List[[time, equity]]`, `trade_row(candles, trade) -> Dict`, `period_metrics(candles, sim, timeframe_ms) -> Dict`, `trade_period(candles, signals, lo, hi, plan, neutral, timeframe_ms) -> Dict`. Period dict keys: `from, to, bars, trades, win_rate, avg_win_r, avg_loss_r, expectancy_r, profit_factor, total_return_pct, max_drawdown_pct, sharpe, exposure_pct, longest_losing_streak, buy_hold_pct, skipped_in_position, skipped_neutral, skipped_no_room, equity, trade_list, trades_listed, flags`. `trade_list` rows: `entry_time, entry, exit_time, exit, direction ("long"|"short"), reason, r, pct, bars`.

- [ ] **Step 1: Failing tests** (append)

```python
from backtest.metrics import max_drawdown_pct, trade_period


def test_metrics_add_up_by_hand():
    candles = bars(FLAT, (100, 105, 99, 104), FLAT, (100, 101, 97, 98), FLAT, FLAT, FLAT, FLAT)
    m = trade_period(candles, [sig(0), sig(2)], 0, 8, plan(), "skip", H)
    assert m["trades"] == 2 and m["win_rate"] == 0.5
    assert (m["expectancy_r"], m["avg_win_r"], m["avg_loss_r"]) == (0.5, 2.0, -1.0)
    assert m["profit_factor"] == 2.0
    assert m["total_return_pct"] == pytest.approx(0.98, abs=1e-3)
    assert m["max_drawdown_pct"] == pytest.approx(-1.0, abs=1e-3)
    assert m["exposure_pct"] == 25.0 and m["longest_losing_streak"] == 1 and m["buy_hold_pct"] == 0.0
    assert [t["reason"] for t in m["trade_list"]] == ["target", "stop"]
    assert m["trade_list"][0]["direction"] == "long" and m["trade_list"][0]["entry_time"] == T0 + H
    assert m["equity"][0] == [T0, 1.0] and m["equity"][-1][1] == pytest.approx(1.0098, abs=1e-5)
    assert m["flags"] == ["too_few_trades"]


def test_drawdown_and_an_account_that_never_traded():
    assert max_drawdown_pct([1.0, 1.2, 0.9, 1.3]) == pytest.approx(-25.0)
    m = trade_period(bars(*[FLAT] * 10), [], 0, 10, plan(), "skip", H)
    assert m["trades"] == 0 and m["sharpe"] is None and m["expectancy_r"] is None
    assert m["profit_factor"] is None and m["equity"][-1][1] == 1.0
```

- [ ] **Step 2:** Run → FAIL (`No module named 'backtest.metrics'`).

- [ ] **Step 3: Implement** `backend/backtest/metrics.py`:

```python
"""
What trading the signals would have done to an account, one period at a time.

Each period starts from an equity of 1.0 so seen and unseen are compared on
equal terms. Drawdown and Sharpe read the mark-to-market equity at every
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
```

- [ ] **Step 4:** Run `python -m pytest tests/test_backtest_trades.py -q` → 14 passed.
- [ ] **Step 5: Commit** `git add backend/backtest/metrics.py backend/tests/test_backtest_trades.py && git commit -m "Trade metrics per period: expectancy, drawdown, Sharpe, equity" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 4: Trades in the report

**Files:** Modify `backend/backtest/runner.py`; Test `backend/tests/test_backtest_runner.py` (append)

**Interfaces:** Report gains `"trades": {"seen": <period>, "unseen": <period>}` and `meta.exit` (the exit plan as a dict).

- [ ] **Step 1: Failing test** (append)

```python
async def test_the_report_carries_trades_for_both_periods():
    report = await runner.run_job(job(), jobs=FakeJobs(), history=FakeHistory(doji_series(900)), chunk=200, to_thread=direct)
    assert set(report["trades"]) == {"seen", "unseen"}
    assert report["meta"]["exit"]["max_bars"] == 20
    seen = report["trades"]["seen"]
    assert seen["trades"] > 0 and seen["equity"][0][1] == 1.0
```

- [ ] **Step 2:** Run `python -m pytest tests/test_backtest_runner.py -q` → FAIL (`KeyError: 'trades'`).

- [ ] **Step 3: Implement.** In `backend/backtest/runner.py` add `from backtest.metrics import trade_period`. In `_run`, replace the final `return {` statement's `"meta"` entry line `"replay_seconds": round(replay_seconds, 1),` with:

```python
            "replay_seconds": round(replay_seconds, 1),
            "exit": request.exit.model_dump(),
```

and replace the line `"study": study(candles, setups, start=start, split=split, end=end, neutral=request.neutral),` with:

```python
        "study": study(candles, setups, start=start, split=split, end=end, neutral=request.neutral),
        "trades": {
            "seen": trade_period(candles, setups, start, split, request.exit, request.neutral, TIMEFRAME_MS[timeframe]),
            "unseen": trade_period(candles, setups, split, end, request.exit, request.neutral, TIMEFRAME_MS[timeframe]),
        },
```

- [ ] **Step 4:** Run the full backend suite → **411 passed**.
- [ ] **Step 5: Commit** `git add backend/backtest/runner.py backend/tests/test_backtest_runner.py && git commit -m "Backtest reports include trades for seen and unseen" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 5: Client types and helpers

**Files:** Modify `frontend/lib/backtests.ts`, `frontend/tests/backtests.test.ts` (append)

**Interfaces:** Produces `ExitPlan`, `DEFAULT_EXIT`, `TradeRow`, `TradePeriod`; `BacktestReport.trades?` and `meta.exit?`; `createBacktest(rule, { neutral, split, exit })`; `TIMEFRAME_MS`, `CHART_BARS`, `fmtR`, `markable(trade, meta)`, `tradeMarks(trade): BarMark[]`, `TRADE_MARKS_EVENT`, `TradeMarksDetail`, `showTradesOnChart(detail)`, `equityLines(seen, unseen, width, height)`, `tradeVerdict(report): string | null`.

- [ ] **Step 1: Failing tests** (append to `frontend/tests/backtests.test.ts`; also extend its import line to `import { canBeNeutral, equityLines, fmtPct, markable, tradeMarks, tradeVerdict, verdict, type BacktestReport, type PeriodStudy, type TradePeriod, type TradeRow } from "@/lib/backtests"`)

```ts
function tp(over: Partial<TradePeriod> = {}): TradePeriod {
  return {
    from: 0, to: 1, bars: 100, trades: 40, win_rate: 0.45, avg_win_r: 2, avg_loss_r: -1, expectancy_r: 0.35,
    profit_factor: 1.6, total_return_pct: 12.5, max_drawdown_pct: -6.2, sharpe: 1.1, exposure_pct: 30,
    longest_losing_streak: 5, buy_hold_pct: 20, skipped_in_position: 0, skipped_neutral: 0, skipped_no_room: 0,
    equity: [], trade_list: [], trades_listed: 0, flags: [],
    ...over,
  }
}

describe("trades", () => {
  const trade: TradeRow = { entry_time: 10_000, entry: 100, exit_time: 20_000, exit: 104, direction: "long", reason: "target", r: 2, pct: 4, bars: 3 }

  it("marks an entry and an exit", () => {
    expect(tradeMarks(trade)).toEqual([
      { type: "bar", time: 10_000, position: "below", shape: "arrowUp", text: "Long" },
      { type: "bar", time: 20_000, position: "above", shape: "circle", text: "+2.00R target" },
    ])
  })

  it("only offers trades inside the chart's loaded window", () => {
    const hour = 3_600_000
    const to = 5000 * hour
    expect(markable({ ...trade, entry_time: to - 100 * hour }, { to, timeframe: "1h" })).toBe(true)
    expect(markable({ ...trade, entry_time: to - 2000 * hour }, { to, timeframe: "1h" })).toBe(false)
  })

  it("draws unseen equity continuing from seen, on a time axis", () => {
    const lines = equityLines([[0, 1], [10, 1.1]], [[10, 1], [20, 0.5]], 100, 50)
    expect(lines.boundaryX).toBe(50)
    expect(lines.seen).toBe("0.0,9.1 50.0,0.0")
    expect(lines.unseen).toBe("50.0,0.0 50.0,0.0 100.0,50.0")
  })

  it("sums up the unseen trades, or says there are too few", () => {
    const base = report(period())
    expect(tradeVerdict({ ...base, trades: { seen: tp({ expectancy_r: 0.5 }), unseen: tp() } })).toBe(
      "Trading it on unseen data: +0.35R per trade over 40 trades, +12.50% total, worst drawdown -6.20% (seen: +0.50R per trade).",
    )
    expect(tradeVerdict({ ...base, trades: { seen: tp(), unseen: tp({ trades: 7, flags: ["too_few_trades"] }) } })).toBe(
      "Only 7 unseen trades — too few to judge this exit plan.",
    )
    expect(tradeVerdict(base)).toBeNull()
  })
})
```

- [ ] **Step 2:** Run `npx vitest run tests/backtests.test.ts` → FAIL (missing exports).

- [ ] **Step 3: Implement.** In `frontend/lib/backtests.ts`:

1. Add `import type { BarMark } from "@/lib/marks"` below the existing imports.
2. In `interface BacktestReport`, add `exit?: ExitPlan` to `meta` and add the field `trades?: { seen: TradePeriod; unseen: TradePeriod }` after `study`.
3. Change `createBacktest`'s `options` type to `{ neutral: Neutral; split: number; exit: ExitPlan }` and add `exit: options.exit,` after `split: options.split,` in the body.
4. Append:

```ts
export interface ExitPlan {
  stop_atr: number | null
  stop_pct: number | null
  target_r: number | null
  target_pct: number | null
  max_bars: number
  exit_on_opposite: boolean
  fee_pct: number
  slippage_pct: number
  risk_pct: number
}

export const DEFAULT_EXIT: ExitPlan = {
  stop_atr: 1.5,
  stop_pct: null,
  target_r: 2,
  target_pct: null,
  max_bars: 20,
  exit_on_opposite: false,
  fee_pct: 0.1,
  slippage_pct: 0.02,
  risk_pct: 1,
}

export interface TradeRow {
  entry_time: number
  entry: number
  exit_time: number
  exit: number
  direction: "long" | "short"
  reason: "stop" | "target" | "time" | "opposite" | "end"
  r: number
  pct: number
  bars: number
}

export interface TradePeriod {
  from: number
  to: number
  bars: number
  trades: number
  win_rate: number | null
  avg_win_r: number | null
  avg_loss_r: number | null
  expectancy_r: number | null
  profit_factor: number | null
  total_return_pct: number | null
  max_drawdown_pct: number | null
  sharpe: number | null
  exposure_pct: number | null
  longest_losing_streak: number
  buy_hold_pct: number | null
  skipped_in_position: number
  skipped_neutral: number
  skipped_no_room: number
  equity: [number, number][]
  trade_list: TradeRow[]
  trades_listed: number
  flags: string[]
}

export const TIMEFRAME_MS: Record<string, number> = {
  "5m": 300_000,
  "15m": 900_000,
  "1h": 3_600_000,
  "1d": 86_400_000,
}

/** Candles the chart loads. A trade older than this cannot be drawn on it. */
export const CHART_BARS = 1000

export function fmtR(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}R`
}

export function markable(trade: TradeRow, meta: { to: number; timeframe: string }): boolean {
  const step = TIMEFRAME_MS[meta.timeframe]
  if (!step) return false
  return trade.entry_time >= meta.to - (CHART_BARS - 10) * step
}

export function tradeMarks(trade: TradeRow): BarMark[] {
  const long = trade.direction === "long"
  return [
    { type: "bar", time: trade.entry_time, position: long ? "below" : "above", shape: long ? "arrowUp" : "arrowDown", text: long ? "Long" : "Short" },
    { type: "bar", time: trade.exit_time, position: long ? "above" : "below", shape: "circle", text: `${fmtR(trade.r)} ${trade.reason}` },
  ]
}

/** The page listens for this and draws the marks on the pair and timeframe they belong to. */
export const TRADE_MARKS_EVENT = "vt:trade-marks"

export interface TradeMarksDetail {
  symbol: string
  timeframe: string
  marks: BarMark[]
}

export function showTradesOnChart(detail: TradeMarksDetail): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<TradeMarksDetail>(TRADE_MARKS_EVENT, { detail }))
  }
}

/**
 * SVG polyline points for the equity curve. Unseen continues from seen's final
 * equity, so the line is unbroken; x is proportional to time.
 */
export function equityLines(
  seen: [number, number][],
  unseen: [number, number][],
  width: number,
  height: number,
): { seen: string; unseen: string; boundaryX: number | null } {
  const carry = seen.length ? seen[seen.length - 1][1] : 1
  const points: [number, number][] = [...seen, ...unseen.map(([t, e]) => [t, e * carry] as [number, number])]
  if (points.length === 0) return { seen: "", unseen: "", boundaryX: null }

  const t0 = points[0][0]
  const t1 = points[points.length - 1][0]
  const values = points.map(([, e]) => e)
  const min = Math.min(...values)
  const span = Math.max(...values) - min || 1
  const x = (t: number) => (t1 === t0 ? 0 : ((t - t0) / (t1 - t0)) * width)
  const y = (e: number) => height - ((e - min) / span) * height
  const text = points.map(([t, e]) => `${x(t).toFixed(1)},${y(e).toFixed(1)}`)

  return {
    seen: text.slice(0, seen.length).join(" "),
    unseen: unseen.length ? text.slice(Math.max(0, seen.length - 1)).join(" ") : "",
    boundaryX: seen.length && unseen.length ? x(seen[seen.length - 1][0]) : null,
  }
}

export function tradeVerdict(report: BacktestReport): string | null {
  if (!report.trades) return null
  const { seen, unseen } = report.trades
  if (unseen.trades === 0) return "No trades on unseen data."
  if (unseen.flags.includes("too_few_trades")) {
    return `Only ${unseen.trades} unseen trades — too few to judge this exit plan.`
  }
  return (
    `Trading it on unseen data: ${fmtR(unseen.expectancy_r)} per trade over ${unseen.trades} trades, ` +
    `${fmtPct(unseen.total_return_pct)} total, worst drawdown ${fmtPct(unseen.max_drawdown_pct)} ` +
    `(seen: ${fmtR(seen.expectancy_r)} per trade).`
  )
}
```

- [ ] **Step 4:** Run `npx vitest run tests/backtests.test.ts` → 10 passed. (The sheet will not type-check until Task 7 passes `exit`; that is expected between these two tasks.)
- [ ] **Step 5: Commit** `git add frontend/lib/backtests.ts frontend/tests/backtests.test.ts && git commit -m "Client types and helpers for backtest trades" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 6: Page-owned trade marks

**Files:** Modify `frontend/components/mark-overlay.tsx`, `frontend/components/price-chart.tsx`, `frontend/app/app/page.tsx`

**Interfaces:** `MarkOverlay` gains prop `loading?: boolean`; bar marks whose time is not a loaded candle are not drawn, and the markers are recomputed when loading finishes. `PriceChart` no longer asks the page to clear marks when its series changes (the owners of marks clear their own); its Clear button still calls `onClearMarks`. The page listens for `TRADE_MARKS_EVENT`, switches the chart to the trades' pair and timeframe, and draws them only while that series is shown.

- [ ] **Step 1: Draw only loaded bars** — in `frontend/components/mark-overlay.tsx`:
  - `interface MarkOverlayProps` gains `loading?: boolean`; the function signature becomes `export default function MarkOverlay({ chart, series, marks, loading = false }: MarkOverlayProps)`.
  - Replace the `barMarks` declaration's first line `const barMarks: SeriesMarker<Time>[] = marks` with:
    ```tsx
    // A marker whose bar is not loaded would be snapped to the nearest bar by
    // the plugin - drawing a trade on the wrong candle. Draw only loaded bars.
    const loaded = new Set(series.data().map((d) => d.time as number))
    const barMarks: SeriesMarker<Time>[] = marks
    ```
    and insert, directly after `.filter((m): m is Extract<Mark, { type: "bar" }> => m.type === "bar")`, the line `.filter((m) => loaded.has(m.time / 1000))`.
  - Change that effect's dependency array from `[series, marks]` to `[series, marks, loading]`.

- [ ] **Step 2: Stop the chart clearing page-owned marks** — in `frontend/components/price-chart.tsx` replace

```tsx
  // Clear drawings when the underlying series changes out from under them.
  useEffect(() => {
    setLevels([])
    setPatterns([])
    setPatternTotal(0)
    onClearMarks?.()
    // onClearMarks is a stable page callback; listing it would re-run this on
    // every render of the page and wipe drawings the user just asked for.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, timeframe])
```

with

```tsx
  // Clear drawings when the underlying series changes out from under them.
  // Assistant and backtest marks belong to the page, which clears the ones
  // that no longer apply; clearing them here would also wipe trades a report
  // just switched the chart to show.
  useEffect(() => {
    setLevels([])
    setPatterns([])
    setPatternTotal(0)
  }, [selected, timeframe])
```

and change `<MarkOverlay chart={chartRef.current} series={seriesRef.current} marks={marks} />` to `<MarkOverlay chart={chartRef.current} series={seriesRef.current} marks={marks} loading={loading} />`.

- [ ] **Step 3: The page owns trade marks** — in `frontend/app/app/page.tsx`:
  - `import { useCallback, useState } from "react"` → `import { useCallback, useEffect, useMemo, useState } from "react"`; add `import { TRADE_MARKS_EVENT, type TradeMarksDetail } from "@/lib/backtests"`.
  - Above `export default function TradingDashboard()` add `const NO_MARKS: Mark[] = []`.
  - Replace

    ```tsx
      const [marks, setMarks] = useState<Mark[]>([])
      const clearMarks = useCallback(() => setMarks([]), [])
    ```

    with

    ```tsx
      const [marks, setMarks] = useState<Mark[]>([])
      // Trades a backtest report asked to draw, tied to the pair and timeframe
      // they happened on: drawn only while the chart shows that series.
      const [tradeMarks, setTradeMarks] = useState<TradeMarksDetail | null>(null)
      const clearMarks = useCallback(() => {
        setMarks([])
        setTradeMarks(null)
      }, [])

      useEffect(() => {
        const onTrades = (event: Event) => {
          const detail = (event as CustomEvent<TradeMarksDetail>).detail
          setCurrentSymbol(detail.symbol)
          setTimeframe(detail.timeframe as Timeframe)
          setTradeMarks(detail)
          setRegion("chart")
        }
        window.addEventListener(TRADE_MARKS_EVENT, onTrades)
        return () => window.removeEventListener(TRADE_MARKS_EVENT, onTrades)
      }, [])

      const shownTradeMarks =
        tradeMarks && tradeMarks.symbol === currentSymbol && tradeMarks.timeframe === timeframe
          ? (tradeMarks.marks as Mark[])
          : NO_MARKS
      const chartMarks = useMemo(
        () => (shownTradeMarks.length ? [...marks, ...shownTradeMarks] : marks),
        [marks, shownTradeMarks],
      )
    ```
  - In `<PriceChart ... />` change `marks={marks}` to `marks={chartMarks}`.

- [ ] **Step 4: Verify** — `npx vitest run` (60 passed) and `npx tsc --noEmit -p .`: expected errors are only the pre-existing `tests/sw.test.ts` one and `components/backtest-sheet.tsx` missing `exit` in `createBacktest` (fixed in Task 7).
- [ ] **Step 5: Commit** `git add frontend/components/mark-overlay.tsx frontend/components/price-chart.tsx frontend/app/app/page.tsx && git commit -m "Page-owned trade marks, drawn only on loaded candles" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 7: The trade report in the sheet

**Files:** Replace `frontend/components/backtest-sheet.tsx`

- [ ] **Step 1: Replace the file** with:

```tsx
"use client"

import { useEffect, useState } from "react"
import { FlaskConical, Loader2, MapPin } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  ACTIVE_STATUSES,
  BACKTEST_TIMEFRAMES,
  DEFAULT_EXIT,
  canBeNeutral,
  cancelBacktest,
  createBacktest,
  equityLines,
  fmtPct,
  fmtR,
  getBacktest,
  markable,
  showTradesOnChart,
  tradeMarks,
  tradeVerdict,
  verdict,
  type Backtest,
  type BacktestReport,
  type BacktestRule,
  type ExitPlan,
  type Neutral,
  type PeriodStudy,
  type TradePeriod,
  type TradeRow,
} from "@/lib/backtests"
import { UnauthorizedError } from "@/lib/rules"
import { cn } from "@/lib/utils"

const POLL_MS = 3000
const SPLITS = [0.6, 0.7, 0.8]
const LISTED = 50
const STAGE: Record<string, string> = {
  queued: "Waiting for the worker",
  replaying: "Replaying history bar by bar",
  studying: "Measuring what followed each signal",
  tuning: "Tuning on seen data",
}

function day(ms: number | null) {
  return ms === null ? "—" : new Date(ms).toISOString().slice(0, 10)
}

function StudyTable({ title, period }: { title: string; period: PeriodStudy }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-semibold text-foreground">{title}</h3>
        <span className="font-mono text-[10px] text-muted-foreground">
          {day(period.from)} → {day(period.to)} · {period.signals} signals
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="text-muted-foreground">
            <tr className="text-left">
              <th className="py-1 pr-2 font-normal">After</th>
              <th className="py-1 pr-2 font-normal">Signal</th>
              <th className="py-1 pr-2 font-normal">Market</th>
              <th className="py-1 pr-2 font-normal">Edge</th>
              <th className="py-1 pr-2 font-normal">95% CI</th>
              <th className="py-1 font-normal">Hit</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {period.horizons.map((h) => (
              <tr key={h.h} className="border-t border-border">
                <td className="py-1 pr-2">{h.h} bars</td>
                <td className="py-1 pr-2">{fmtPct(h.mean_pct)}</td>
                <td className="py-1 pr-2 text-muted-foreground">{fmtPct(h.baseline_pct)}</td>
                <td className={cn("py-1 pr-2", (h.edge_pct ?? 0) > 0 ? "text-emerald-500" : "text-red-400")}>
                  {fmtPct(h.edge_pct)}
                </td>
                <td className="py-1 pr-2 text-muted-foreground">
                  {h.ci_pct ? `${fmtPct(h.ci_pct[0])} … ${fmtPct(h.ci_pct[1])}` : "—"}
                </td>
                <td className="py-1">{h.hit_rate === null ? "—" : `${Math.round(h.hit_rate * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-muted-foreground">
        Moved for it {period.mfe_atr?.toFixed(2) ?? "—"} ATR, against it {period.mae_atr?.toFixed(2) ?? "—"} ATR
        within 20 bars
        {period.skipped_neutral > 0 && ` · ${period.skipped_neutral} directionless signals skipped`}
        {period.flags.includes("too_few_signals") && " · too few signals to judge"}
      </p>
    </div>
  )
}

function NumberField({
  label,
  value,
  step,
  onChange,
}: {
  label: string
  value: number | null
  step: number
  onChange: (value: number) => void
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <Input
        type="number"
        inputMode="decimal"
        step={step}
        min={0}
        value={value ?? ""}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-7 px-2 font-mono text-xs"
      />
    </label>
  )
}

const METRICS: { label: string; get: (p: TradePeriod) => string }[] = [
  { label: "Trades", get: (p) => String(p.trades) },
  { label: "Win rate", get: (p) => (p.win_rate === null ? "—" : `${Math.round(p.win_rate * 100)}%`) },
  { label: "Per trade", get: (p) => fmtR(p.expectancy_r) },
  { label: "Avg win / loss", get: (p) => `${fmtR(p.avg_win_r)} / ${fmtR(p.avg_loss_r)}` },
  { label: "Profit factor", get: (p) => p.profit_factor?.toFixed(2) ?? "—" },
  { label: "Return", get: (p) => fmtPct(p.total_return_pct) },
  { label: "Max drawdown", get: (p) => fmtPct(p.max_drawdown_pct) },
  { label: "Sharpe", get: (p) => p.sharpe?.toFixed(2) ?? "—" },
  { label: "Time in market", get: (p) => (p.exposure_pct === null ? "—" : `${Math.round(p.exposure_pct)}%`) },
  { label: "Longest losing run", get: (p) => String(p.longest_losing_streak) },
  { label: "Buy & hold", get: (p) => fmtPct(p.buy_hold_pct) },
]

function MetricsTable({ seen, unseen }: { seen: TradePeriod; unseen: TradePeriod }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead className="text-muted-foreground">
          <tr className="text-left">
            <th className="py-1 pr-2 font-normal" />
            <th className="py-1 pr-2 font-normal">Unseen</th>
            <th className="py-1 font-normal">Seen</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {METRICS.map((m) => (
            <tr key={m.label} className="border-t border-border">
              <td className="py-1 pr-2 font-sans text-muted-foreground">{m.label}</td>
              <td className="py-1 pr-2">{m.get(unseen)}</td>
              <td className="py-1">{m.get(seen)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EquityChart({ seen, unseen }: { seen: TradePeriod; unseen: TradePeriod }) {
  const width = 300
  const height = 80
  const lines = equityLines(seen.equity, unseen.equity, width, height)
  return (
    <div className="space-y-1">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-20 w-full" aria-label="Equity curve, seen then unseen">
        {lines.boundaryX !== null && (
          <line x1={lines.boundaryX} x2={lines.boundaryX} y1={0} y2={height} className="stroke-border" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
        )}
        <polyline points={lines.seen} fill="none" className="stroke-muted-foreground" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
        <polyline points={lines.unseen} fill="none" className="stroke-primary" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between font-mono text-[10px] text-muted-foreground">
        <span>seen</span>
        <span>unseen →</span>
      </div>
    </div>
  )
}

function TradeList({
  period,
  meta,
  onMark,
}: {
  period: TradePeriod
  meta: BacktestReport["meta"]
  onMark: (trades: TradeRow[]) => void
}) {
  const rows = period.trade_list.slice(-LISTED).reverse()
  const recent = period.trade_list.filter((t) => markable(t, meta)).slice(-LISTED)
  if (rows.length === 0) return <p className="text-[11px] text-muted-foreground">No trades in this period.</p>
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-muted-foreground">
          Latest {rows.length} of {period.trades}
        </span>
        {recent.length > 0 && (
          <Button size="sm" variant="outline" className="h-6 gap-1 px-2 text-[11px]" onClick={() => onMark(recent)}>
            <MapPin className="h-3 w-3" /> Mark {recent.length} on chart
          </Button>
        )}
      </div>
      <div className="max-h-64 overflow-auto">
        <table className="w-full text-[11px]">
          <tbody className="font-mono">
            {rows.map((t, k) => (
              <tr key={`${t.entry_time}-${k}`} className="border-t border-border">
                <td className="py-1 pr-2 whitespace-nowrap">{new Date(t.entry_time).toISOString().slice(0, 16).replace("T", " ")}</td>
                <td className="py-1 pr-2">{t.direction === "long" ? "L" : "S"}</td>
                <td className={cn("py-1 pr-2", t.r > 0 ? "text-emerald-500" : "text-red-400")}>{fmtR(t.r)}</td>
                <td className="py-1 pr-2 font-sans text-muted-foreground">{t.reason}</td>
                <td className="py-1 text-right">
                  {markable(t, meta) ? (
                    <button type="button" onClick={() => onMark([t])} className="text-primary" aria-label="Mark this trade on the chart">
                      <MapPin className="inline h-3 w-3" />
                    </button>
                  ) : (
                    <span className="text-muted-foreground/50" title="Older than the candles the chart loads">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function BacktestSheet({
  rule,
  open,
  onOpenChange,
}: {
  rule: BacktestRule | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [neutral, setNeutral] = useState<Neutral>("skip")
  const [split, setSplit] = useState(0.7)
  const [exitPlan, setExitPlan] = useState<ExitPlan>(DEFAULT_EXIT)
  const [tradesPeriod, setTradesPeriod] = useState<"unseen" | "seen">("unseen")
  const [job, setJob] = useState<Backtest | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  // Closing the sheet forgets the view, not the job: it keeps running on the
  // server. Slice 4 adds a list to reopen it from.
  useEffect(() => {
    if (!open) {
      setJob(null)
      setError(null)
      setStarting(false)
    }
  }, [open])

  const jobId = job?.id
  const running = job !== null && ACTIVE_STATUSES.includes(job.status)
  useEffect(() => {
    if (!jobId || !running) return
    const timer = setInterval(async () => {
      try {
        setJob(await getBacktest(jobId))
      } catch (err) {
        setError(err instanceof Error ? err.message : "Lost track of the backtest")
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [jobId, running])

  if (!rule) return null
  const supported = (BACKTEST_TIMEFRAMES as readonly string[]).includes(rule.timeframe)
  const neutralChoice = canBeNeutral(rule.params)
  const setExit = (patch: Partial<ExitPlan>) => setExitPlan((plan) => ({ ...plan, ...patch }))

  async function start() {
    if (!rule) return
    setStarting(true)
    setError(null)
    try {
      const { id } = await createBacktest(rule, { neutral, split, exit: exitPlan })
      setJob(await getBacktest(id))
    } catch (err) {
      setError(
        err instanceof UnauthorizedError
          ? "Sign in with your wallet in the Strategy panel first."
          : err instanceof Error
            ? err.message
            : "Could not start the backtest",
      )
    } finally {
      setStarting(false)
    }
  }

  async function cancel() {
    if (!job) return
    try {
      await cancelBacktest(job.id)
      setJob({ ...job, status: "cancelled" })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel")
    }
  }

  function mark(trades: TradeRow[]) {
    if (!job?.report) return
    showTradesOnChart({
      symbol: job.report.meta.symbol,
      timeframe: job.report.meta.timeframe,
      marks: trades.flatMap(tradeMarks),
    })
    onOpenChange(false)
  }

  const report = job?.status === "done" ? job.report : null

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-primary" /> Backtest
          </SheetTitle>
          <SheetDescription>
            {rule.name} · {rule.symbol} {rule.timeframe}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 px-4 pb-6">
          {!supported && <p className="text-xs text-muted-foreground">Backtests run on 5m, 15m, 1h and 1d charts.</p>}

          {supported && job === null && (
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-muted-foreground">
                Replays this rule over stored history exactly as the live alert would have run, measures what price
                did after each signal, and trades it with the exit plan below. The last part of history is held back
                as unseen data.
              </p>
              {neutralChoice && (
                <div className="space-y-1">
                  <span className="text-[11px] text-muted-foreground">This candle has no direction. Read it as</span>
                  <div className="flex gap-1.5">
                    {(["skip", "long", "short"] as Neutral[]).map((n) => (
                      <Button key={n} size="sm" variant={neutral === n ? "default" : "outline"} className="h-7 flex-1 text-xs" onClick={() => setNeutral(n)}>
                        {n === "skip" ? "Skip it" : n === "long" ? "Long" : "Short"}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Exit plan</span>
                <div className="grid grid-cols-3 gap-2">
                  <NumberField label="Stop (× ATR)" value={exitPlan.stop_atr} step={0.25} onChange={(v) => setExit({ stop_atr: v > 0 ? v : DEFAULT_EXIT.stop_atr })} />
                  <NumberField label="Target (× risk)" value={exitPlan.target_r} step={0.5} onChange={(v) => setExit({ target_r: v > 0 ? v : null })} />
                  <NumberField label="Max bars held" value={exitPlan.max_bars} step={1} onChange={(v) => setExit({ max_bars: Math.max(1, Math.round(v) || 1) })} />
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <NumberField label="Fee per side %" value={exitPlan.fee_pct} step={0.01} onChange={(v) => setExit({ fee_pct: Math.max(0, v) })} />
                  <NumberField label="Slippage %" value={exitPlan.slippage_pct} step={0.01} onChange={(v) => setExit({ slippage_pct: Math.max(0, v) })} />
                  <NumberField label="Risk per trade %" value={exitPlan.risk_pct} step={0.25} onChange={(v) => setExit({ risk_pct: v > 0 ? v : DEFAULT_EXIT.risk_pct })} />
                </div>
              </div>
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Seen / unseen split</span>
                <div className="flex gap-1.5">
                  {SPLITS.map((s) => (
                    <Button key={s} size="sm" variant={split === s ? "default" : "outline"} className="h-7 flex-1 font-mono text-xs" onClick={() => setSplit(s)}>
                      {Math.round(s * 100)} / {Math.round((1 - s) * 100)}
                    </Button>
                  ))}
                </div>
              </div>
              <Button onClick={start} disabled={starting} className="h-9 w-full text-xs">
                {starting ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="mr-1 h-3.5 w-3.5" />}
                Run backtest
              </Button>
            </div>
          )}

          {job && ACTIVE_STATUSES.includes(job.status) && (
            <div className="space-y-2">
              <p className="text-xs text-foreground">{STAGE[job.status]}…</p>
              <Progress value={Math.round(job.progress * 100)} />
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] text-muted-foreground">{Math.round(job.progress * 100)}%</span>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={cancel}>
                  Cancel
                </Button>
              </div>
              <p className="text-[10px] text-muted-foreground">
                The first run of a rule replays every bar and can take many minutes. It keeps running if you close this.
              </p>
            </div>
          )}

          {job?.status === "failed" && <p className="text-xs text-destructive">{job.error}</p>}
          {job?.status === "cancelled" && <p className="text-xs text-muted-foreground">Cancelled.</p>}

          {report && (
            <div className="space-y-5">
              <div className="space-y-2 rounded-md border border-border bg-secondary px-3 py-2 text-xs text-foreground">
                <p>{verdict(report)}</p>
                {tradeVerdict(report) && <p>{tradeVerdict(report)}</p>}
              </div>

              {report.trades && (
                <section className="space-y-3">
                  <h3 className="text-xs font-semibold text-foreground">Trading it</h3>
                  <EquityChart seen={report.trades.seen} unseen={report.trades.unseen} />
                  <MetricsTable seen={report.trades.seen} unseen={report.trades.unseen} />
                  <div className="flex gap-1.5">
                    {(["unseen", "seen"] as const).map((p) => (
                      <Button key={p} size="sm" variant={tradesPeriod === p ? "default" : "outline"} className="h-6 flex-1 text-[11px] capitalize" onClick={() => setTradesPeriod(p)}>
                        {p} trades
                      </Button>
                    ))}
                  </div>
                  <TradeList period={report.trades[tradesPeriod]} meta={report.meta} onMark={mark} />
                </section>
              )}

              <section className="space-y-3">
                <h3 className="text-xs font-semibold text-foreground">Does the signal predict anything?</h3>
                <StudyTable title="Unseen" period={report.study.unseen} />
                <StudyTable title="Seen" period={report.study.seen} />
              </section>

              <p className="text-[10px] leading-relaxed text-muted-foreground">
                {report.signals.fires} alerts from {report.signals.setups} distinct setups over{" "}
                {report.meta.bars.toLocaleString()} bars; each setup counts and trades once. Fills assume the worse
                case inside a bar and pay fees and slippage.{" "}
                {report.meta.tape_cached ? "Replay reused from cache." : `Replay took ${Math.round(report.meta.replay_seconds)}s.`}{" "}
                Past behaviour on this data is not a forecast.
              </p>
            </div>
          )}

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 2: Verify** — `npx tsc --noEmit -p .` (only `tests/sw.test.ts`), `npx vitest run` (**60 passed**), `npx next build` (succeeds).
- [ ] **Step 3: Commit** `git add frontend/components/backtest-sheet.tsx && git commit -m "Trade report in the backtest sheet: equity, metrics, trades on the chart" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 8: Record, ship, verify

- [ ] **Step 1: Spec.** Under "4. Trade model" append a paragraph `*(Slice 3 decisions:)*` listing decisions 1–5 from the top of this plan. Commit `Record slice 3's decisions in the backtesting spec`.
- [ ] **Step 2: Green, scan, PR, merge.** Backend 411, frontend 60, build clean; `git diff origin/main | grep -E "^\+" | grep -iE "csk-|gsk_|JWT_SECRET=[A-Za-z0-9]{8,}"` shows only plan text; push `feature/backtesting-slice3`, open PR "Backtesting slice 3: trade model and metrics", merge.
- [ ] **Step 3: Deploy** backend and backtester exactly as slice 2's Task 12 Step 3; both healthy.
- [ ] **Step 4: Real run on prod.** Mint a throwaway session inside the backend container (`issue_token("0x…dead")["token"]`, kept in a shell variable only). Submit the BTCUSDT 1h doji rule with `"neutral": "long"` — the slice 2 tape for it is cached, so it completes in seconds — and check: `report.trades.seen.trades` and `unseen.trades` > 0; `equity` starts at 1.0; `trade_list` reasons ⊆ {stop, target, time, end}; `meta.exit.max_bars == 20`; every `r` is finite. Submit again with `"exit": {"stop_pct": 1, "target_pct": 2, "max_bars": 10}` and confirm the trade counts or results change and the tape is still reused. Delete the jobs.
- [ ] **Step 5: Browser.** On app.vibetrading.club signed in: run a backtest on a 1h rule; the report shows both verdict lines, the equity curve with a boundary, the metrics table and trade list; **Mark N on chart** closes the sheet, switches the chart to the pair and timeframe, and draws arrows and exit circles on recent candles only; the chart's Clear removes them.
