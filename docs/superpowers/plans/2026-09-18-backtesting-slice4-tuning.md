# Backtesting Slice 4: Tuning on Seen Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A backtest can search a grid of exit plans and rule filters **on seen data only**, run the single best one **once** on unseen data, and report how much it degraded — with the number of settings tried always in view, an overfit flag when unseen is far worse, and a list of recent backtests to reopen.

**Architecture:** A pure tuner (`backtest/tuning.py`) is handed candles only up to the split boundary, groups the grid by rule filter so each filter's signals are derived from the cached tape once, then simulates each exit combination over the seen slice. The runner uses the winner for the report it already produces, adds a `tuning` section and top-level `flags`. The frontend gains a tuning card, a reopen-by-id path for the sheet, and a Backtests tab in the Strategy panel; the risk and architecture pages describe what a tuned number means.

**Tech Stack:** Python 3.11, numpy, pytest; Next.js 15, React 19, shadcn/ui, vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-backtesting-design.md` — "6. Seen/unseen tuning", "Metrics → Honesty flags", "UI", "Testing", "Slices → 4". Slices 1–3 are live: `signals_from_tape`, `distinct_setups`, `study`, `trade_period`, `simulate`, `ExitPlan`, `BacktestCreate`, `run_job`, `lib/backtests.ts`, `components/backtest-sheet.tsx`, `components/analysis-panel.tsx`.

## Global Constraints

- **The unseen lock:** `tune()` receives `candles[: split + 1]` — everything up to and including the boundary bar, whose open closes a trade still held at the split (slice 3's rule) — and nothing beyond. No other unseen value is available to it.
- Grid defaults: `stop_atr [1, 1.5, 2]`, `target_r [1, 2, 3]`, `max_bars [10, 20, 40]`, plus the rule's own filter: pattern `min_confidence [60, 70, 80]`, liquidity `min_strength ["weak", "medium", "strong"]`, sequence none. `MAX_COMBINATIONS = 200`; a larger grid is a **422**.
- Objective: highest seen `expectancy_r` among settings with at least `MIN_TRADES` (30) seen trades; ties broken by the smaller seen drawdown. If nothing qualifies, the setting with the most trades is chosen and the report says so.
- Tuning searches ATR stops and R targets: percentage stop/target are cleared in the tuned plan.
- Flags on the report: `likely_overfit` when seen expectancy is positive and unseen is below half of it (or of the opposite sign); `tuned` whenever a grid was searched.
- **Only the chosen setting is ever run on unseen data.** The top five are reported on seen only.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; scan staged diffs for `csk-`, `gsk_`, `JWT_SECRET=`.

**Running tests.** Backend from `backend/`: `python -m pytest -q` (baseline **411**). Frontend from `frontend/`: `npx vitest run` (baseline **60**), `npx tsc --noEmit -p .` (only the pre-existing `tests/sw.test.ts` error), `npx next build`.

## Decisions this plan makes

Record in the spec in Task 7.

1. **Tuning is on by default** in the sheet (the spec's UI section), because the cached tape makes it cheap — and every report states how many settings were tried, so a tuned number is never presented as an untuned one.
2. **The grid is searched by filter group.** Signals depend only on the rule filter, exits only on the plan, so each filter's signals are derived once and reused across exit combinations.
3. **Percentage stops are not tuned.** A grid mixing ATR and percentage stops would not compare like with like; a percentage stop remains available for a single untuned run.
4. **`tuning.top` reports seen metrics only.** Running the runners-up on unseen data would turn unseen into a second tuning set.
5. Repeating a backtest an hour later still replays from scratch (the tape is keyed to the newest candle). Fixing that by extending tapes bar by bar is **out of scope here** and is its own slice.

## File Structure

| File | Responsibility |
|---|---|
| Modify `backend/models/backtest_schemas.py` | `Grid`, `MAX_COMBINATIONS`, `BacktestCreate.tune/grid` + size validation. |
| Create `backend/backtest/tuning.py` | `Setting`, `combinations`, `filter_values`, `plan_for`, `tune`. |
| Modify `backend/backtest/runner.py` | Tune stage, chosen setting, `tuning` section, `flags`. |
| Create `backend/tests/test_backtest_tuning.py`; modify `test_backtest_schemas.py`, `test_backtest_runner.py` | Tests. |
| Modify `frontend/lib/backtests.ts`, `frontend/tests/backtests.test.ts` | `Grid`, `TuningReport`, `verdict` prefix, `overfit`. |
| Modify `frontend/components/backtest-sheet.tsx` | Tune toggle, tuning card, reopen by job id. |
| Modify `frontend/components/analysis-panel.tsx` | Backtests tab. |
| Modify `frontend/app/legal/risk/page.tsx`, `frontend/app/architecture/page.tsx` | What a tuned result means. |

---

### Task 1: The grid

**Files:** Modify `backend/models/backtest_schemas.py`; Test `backend/tests/test_backtest_schemas.py` (append)

**Interfaces:** Produces `MAX_COMBINATIONS = 200`; `class Grid(BaseModel)` with `stop_atr: List[float]`, `target_r: List[float]`, `max_bars: List[int]`, `min_confidence: List[float]`, `min_strength: List[str]` (each non-empty, ≤ 10 entries); `BacktestCreate.tune: bool = False`, `BacktestCreate.grid: Grid = Grid()`, and a validator rejecting a grid whose combination count for this rule's agent exceeds the cap. Produces `grid_size(grid, agent) -> int`.

- [ ] **Step 1: Failing tests** (append)

```python
def test_grid_defaults_and_size_per_agent():
    from models.backtest_schemas import grid_size

    body = BacktestCreate(rule=RULE, tune=True)
    assert body.grid.stop_atr == [1.0, 1.5, 2.0] and body.grid.target_r == [1.0, 2.0, 3.0]
    assert body.grid.max_bars == [10, 20, 40]
    # A sequence rule has no filter of its own: 3 x 3 x 3.
    assert grid_size(body.grid, "sequence") == 27
    assert grid_size(body.grid, "pattern") == 81
    assert grid_size(body.grid, "liquidity") == 81


def test_a_grid_over_the_cap_is_refused():
    big = {"stop_atr": [0.5, 1, 1.5, 2, 2.5, 3], "target_r": [1, 1.5, 2, 2.5, 3, 4], "max_bars": [5, 10, 20, 40, 80, 160]}
    with pytest.raises(ValidationError, match="216 combinations"):
        BacktestCreate(rule=RULE, tune=True, grid=big)


def test_an_empty_grid_axis_is_refused():
    with pytest.raises(ValidationError):
        BacktestCreate(rule=RULE, tune=True, grid={"stop_atr": []})
```

- [ ] **Step 2:** Run `python -m pytest tests/test_backtest_schemas.py -q` → FAIL (`cannot import name 'grid_size'`).

- [ ] **Step 3: Implement.** In `backend/models/backtest_schemas.py`: change the typing import to `from typing import List, Literal, Optional, Tuple`, and add after `ExitPlan`:

```python
# The most settings one job may search. Each one is cheap against a cached
# tape, but the report has to stay readable and the queue has to keep moving.
MAX_COMBINATIONS = 200


class Grid(BaseModel):
    """
    What tuning is allowed to vary. The rule's own filter is varied too, by
    agent: confidence for patterns, level strength for liquidity, nothing for
    sequences - a sequence step is either matched or it is not.
    """

    stop_atr: List[float] = Field(default=[1.0, 1.5, 2.0], min_length=1, max_length=10)
    target_r: List[float] = Field(default=[1.0, 2.0, 3.0], min_length=1, max_length=10)
    max_bars: List[int] = Field(default=[10, 20, 40], min_length=1, max_length=10)
    min_confidence: List[float] = Field(default=[60.0, 70.0, 80.0], min_length=1, max_length=10)
    min_strength: List[Literal["weak", "medium", "strong"]] = Field(
        default=["weak", "medium", "strong"], min_length=1, max_length=10
    )


def grid_size(grid: Grid, agent: str) -> int:
    filters = {"pattern": len(grid.min_confidence), "liquidity": len(grid.min_strength)}.get(agent, 1)
    return len(grid.stop_atr) * len(grid.target_r) * len(grid.max_bars) * filters
```

In `BacktestCreate`, after `exit`, add:

```python
    # Search the grid on seen data and verify the winner once on unseen data.
    tune: bool = False
    grid: Grid = Field(default_factory=Grid)
```

and extend the existing `_timeframe_has_history` validator body (before its `return self`) with:

```python
        if self.tune:
            size = grid_size(self.grid, self.rule.params.agent)
            if size > MAX_COMBINATIONS:
                raise ValueError(
                    f"That grid is {size} combinations; at most {MAX_COMBINATIONS} can be searched"
                )
```

- [ ] **Step 4:** Run → 10 passed.
- [ ] **Step 5: Commit** `git add backend/models/backtest_schemas.py backend/tests/test_backtest_schemas.py && git commit -m "A bounded grid for backtest tuning" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 2: The tuner

**Files:** Create `backend/backtest/tuning.py`; Test `backend/tests/test_backtest_tuning.py`

**Interfaces:**
- Consumes: `signals_from_tape`, `distinct_setups`, `simulate`, `period_metrics`, `MIN_TRADES`, `Grid`, `ExitPlan`, `grid_size`.
- Produces:
  - `@dataclass(frozen=True) Setting(filters: Dict[str, Any], stop_atr: float, target_r: float, max_bars: int)` with `as_dict()`
  - `filter_values(grid, agent) -> List[Dict[str, Any]]`
  - `combinations(grid, agent) -> List[Setting]`
  - `plan_for(plan: ExitPlan, setting: Setting) -> ExitPlan`
  - `tune(candles, tape, params, plan, *, neutral, start, split, grid, timeframe_ms, persist_bars, cooldown_secs, progress=None) -> Dict` where `candles` **must** be `candles[: split + 1]`; returns `{tried, objective, min_trades, qualified, chosen: {...}, top: [{settings, trades, expectancy_r, max_drawdown_pct, total_return_pct}]}`.

- [ ] **Step 1: Failing tests** — `backend/tests/test_backtest_tuning.py`:

```python
"""Tuning: every setting tried on seen data, the winner picked honestly, unseen untouched."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.replay import first_index, replay_range
from backtest.tuning import combinations, filter_values, plan_for, tune
from models.backtest_schemas import ExitPlan, Grid
from models.rule_schemas import RuleCreate
from walks import doji_series, random_walk


def params_for(raw):
    return RuleCreate(name="t", symbol="BTCUSDT", timeframe="1h", params=raw).params.model_dump()


DOJI = params_for({"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}], "lookback": 60})
PATTERNS = params_for({"agent": "pattern", "kinds": ["W", "M"], "states": ["confirmed"], "lookback": 150})
PLAN = ExitPlan(fee_pct=0, slippage_pct=0)


def test_filter_values_follow_the_agent():
    grid = Grid()
    assert filter_values(grid, "sequence") == [{}]
    assert filter_values(grid, "pattern") == [{"min_confidence": 60.0}, {"min_confidence": 70.0}, {"min_confidence": 80.0}]
    assert filter_values(grid, "liquidity") == [{"min_strength": "weak"}, {"min_strength": "medium"}, {"min_strength": "strong"}]


def test_combinations_cover_the_grid_in_a_stable_order():
    grid = Grid(stop_atr=[1, 2], target_r=[1], max_bars=[10, 20])
    settings = combinations(grid, "sequence")
    assert [(s.stop_atr, s.max_bars) for s in settings] == [(1.0, 10), (1.0, 20), (2.0, 10), (2.0, 20)]
    assert combinations(grid, "pattern")[0].filters == {"min_confidence": 60.0}


def test_plan_for_replaces_the_exits_and_drops_percentage_modes():
    plan = plan_for(ExitPlan(stop_pct=1, target_pct=2, max_bars=5, fee_pct=0.2), combinations(Grid(), "sequence")[0])
    assert (plan.stop_atr, plan.target_r, plan.max_bars) == (1.0, 1.0, 10)
    assert plan.stop_pct is None and plan.target_pct is None
    assert plan.fee_pct == 0.2  # costs are not tuned


def tuned(candles, params, split, grid=None, **kw):
    start = first_index(params)
    tape = replay_range(candles, params, start, len(candles))
    return tune(
        candles[: split + 1], tape, params, PLAN,
        neutral="long", start=start, split=split, grid=grid or Grid(stop_atr=[1, 2], target_r=[1, 2], max_bars=[10, 20]),
        timeframe_ms=3_600_000, persist_bars=0, cooldown_secs=0, **kw,
    )


def test_tuning_reports_every_setting_and_ranks_the_best_first():
    candles = doji_series(1200)
    result = tuned(candles, DOJI, 800)
    assert result["tried"] == 8 and len(result["top"]) == 5
    scores = [row["expectancy_r"] for row in result["top"]]
    assert scores == sorted(scores, reverse=True)
    assert result["chosen"] == result["top"][0]["settings"]
    assert all(row["trades"] > 0 for row in result["top"])


def test_progress_is_reported_for_every_setting():
    seen = []
    tuned(doji_series(1200), DOJI, 800, progress=lambda done, total: seen.append((done, total)))
    assert seen[0] == (1, 8) and seen[-1] == (8, 8)


def test_a_grid_where_nothing_reaches_the_minimum_says_so():
    # 62 evaluated bars hold about a dozen dojis - nowhere near MIN_TRADES.
    result = tuned(doji_series(300), DOJI, 120)
    assert result["qualified"] is False
    assert result["chosen"]["max_bars"] in (10, 20)


def test_the_tuner_cannot_see_past_the_boundary_bar(monkeypatch):
    candles = doji_series(1200)
    split = 800
    start = first_index(DOJI)
    tape = replay_range(candles, DOJI, start, len(candles))
    seen_slice = candles[: split + 1]

    class Tripwire(list):
        def __getitem__(self, item):
            if isinstance(item, int) and item > split:
                raise AssertionError(f"tuner read bar {item}, past the boundary")
            return list.__getitem__(self, item)

    result = tune(
        Tripwire(seen_slice), tape, DOJI, PLAN, neutral="long", start=start, split=split,
        grid=Grid(stop_atr=[1], target_r=[2], max_bars=[20]), timeframe_ms=3_600_000,
        persist_bars=0, cooldown_secs=0,
    )
    assert result["tried"] == 1


def test_pattern_filters_change_the_signals_that_are_traded():
    candles = random_walk(900, seed=7)
    grid = Grid(stop_atr=[1.5], target_r=[2], max_bars=[20], min_confidence=[0, 95])
    result = tuned(candles, PATTERNS, 600, grid=grid)
    assert result["tried"] == 2
    counts = {row["settings"]["filters"]["min_confidence"]: row["trades"] for row in result["top"]}
    assert counts[0.0] >= counts[95.0]
```

- [ ] **Step 2:** Run `python -m pytest tests/test_backtest_tuning.py -q` → FAIL (`No module named 'backtest.tuning'`).

- [ ] **Step 3: Implement** `backend/backtest/tuning.py`:

```python
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
```

- [ ] **Step 4:** Run `python -m pytest tests/test_backtest_tuning.py -q` → 8 passed. The tripwire test is the unseen lock: if it fails, the tuner is reading past the boundary and that must be fixed, never the test.
- [ ] **Step 5: Commit** `git add backend/backtest/tuning.py backend/tests/test_backtest_tuning.py && git commit -m "Tune exits and filters on seen data only" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 3: The runner tunes, then verifies once

**Files:** Modify `backend/backtest/runner.py`; Test `backend/tests/test_backtest_runner.py` (append)

**Interfaces:** When `request.tune`, the runner sets status `tuning`, runs `tune` in a worker thread over `candles[: split + 1]`, then builds the report's `study` and `trades` with the chosen filter and plan. Report gains `"tuning": {...}` (or absent when not tuned) and `"flags": [...]`; `meta.exit` becomes the plan actually used and `meta.params` the filtered params.

- [ ] **Step 1: Failing tests** (append)

```python
TUNED = {**REQUEST, "tune": True, "grid": {"stop_atr": [1, 2], "target_r": [1, 2], "max_bars": [10, 20]}}


async def test_a_tuned_job_reports_what_it_tried_and_uses_the_winner():
    jobs = FakeJobs()
    report = await runner.run_job({"id": "t1", "request": TUNED}, jobs=jobs, history=FakeHistory(doji_series(1200)),
                                  chunk=300, to_thread=direct)
    tuning = report["tuning"]
    assert tuning["tried"] == 8 and len(tuning["top"]) == 5
    assert "tuned" in report["flags"]
    chosen = tuning["chosen"]
    assert (report["meta"]["exit"]["stop_atr"], report["meta"]["exit"]["max_bars"]) == (chosen["stop_atr"], chosen["max_bars"])
    assert report["meta"]["exit"]["stop_pct"] is None
    assert [s for s, _ in jobs.progress].count("tuning") >= 1


async def test_an_untuned_job_has_no_tuning_section():
    report = await runner.run_job(job(), jobs=FakeJobs(), history=FakeHistory(doji_series(900)), chunk=300, to_thread=direct)
    assert "tuning" not in report and "tuned" not in report["flags"]


def test_overfit_flag_reads_seen_against_unseen():
    assert "likely_overfit" in runner.report_flags({"seen": {"expectancy_r": 0.4}, "unseen": {"expectancy_r": 0.1}}, tuned=True)
    assert "likely_overfit" in runner.report_flags({"seen": {"expectancy_r": 0.4}, "unseen": {"expectancy_r": -0.2}}, tuned=False)
    assert "likely_overfit" not in runner.report_flags({"seen": {"expectancy_r": 0.4}, "unseen": {"expectancy_r": 0.35}}, tuned=True)
    assert "likely_overfit" not in runner.report_flags({"seen": {"expectancy_r": -0.1}, "unseen": {"expectancy_r": -0.5}}, tuned=False)
    assert "likely_overfit" not in runner.report_flags({"seen": {"expectancy_r": None}, "unseen": {"expectancy_r": None}}, tuned=True)
```

- [ ] **Step 2:** Run `python -m pytest tests/test_backtest_runner.py -q` → FAIL (`KeyError: 'tuning'`, `no attribute 'report_flags'`).

- [ ] **Step 3: Implement.** In `backend/backtest/runner.py`:

1. Add imports: `from backtest.tuning import plan_for, tune` and `from models.backtest_schemas import BacktestCreate, Grid, required_bars` (extend the existing import).
2. Add above `run_job`:

```python
# A tuned result is the best of many tries; an untuned one is a single
# measurement. Either way the unseen period is the honest half, and a large
# drop from seen to unseen is the signature of a setting fitted to noise.
OVERFIT_RATIO = 0.5


def report_flags(trades: Dict[str, Any], *, tuned: bool) -> List[str]:
    flags = ["tuned"] if tuned else []
    seen = trades["seen"].get("expectancy_r")
    unseen = trades["unseen"].get("expectancy_r")
    if seen is not None and unseen is not None and seen > 0 and unseen < seen * OVERFIT_RATIO:
        flags.append("likely_overfit")
    return flags
```

3. In `_run`, after the `await _checkpoint(job, jobs, "studying", 1.0, clock, started)` line, replace the block that computes `fires`, `setups` and the returned dict with:

```python
    tuning: Optional[Dict[str, Any]] = None
    active_params, active_plan = params, request.exit

    if request.tune:
        await _checkpoint(job, jobs, "tuning", 0.0, clock, started)
        def run_tuning() -> Dict[str, Any]:
            return tune(
                candles[: split + 1], tape, params, request.exit,
                neutral=request.neutral,
                start=start,
                split=split,
                grid=request.grid,
                timeframe_ms=TIMEFRAME_MS[timeframe],
                persist_bars=rule.resolved_persist_bars(),
                cooldown_secs=rule.cooldown_secs,
            )

        tuning = await to_thread(run_tuning)
        active_params = {**params, **tuning["chosen"]["filters"]}
        active_plan = plan_for(request.exit, _setting(tuning["chosen"]))
        await _checkpoint(job, jobs, "studying", 1.0, clock, started)

    fires = signals_from_tape(
        tape, candles, active_params,
        timeframe_ms=TIMEFRAME_MS[timeframe],
        persist_bars=rule.resolved_persist_bars(),
        cooldown_secs=rule.cooldown_secs,
        start=start, end=end,
    )
    setups = distinct_setups(fires)
    trades = {
        "seen": trade_period(candles, setups, start, split, active_plan, request.neutral, TIMEFRAME_MS[timeframe]),
        "unseen": trade_period(candles, setups, split, end, active_plan, request.neutral, TIMEFRAME_MS[timeframe]),
    }

    report: Dict[str, Any] = {
        "meta": {
            "symbol": symbol,
            "timeframe": timeframe,
            "name": rule.name,
            "params": active_params,
            "neutral": request.neutral,
            "split": request.split,
            "bars": end - start,
            "warmup_bars": start,
            "from": int(candles[start]["time"]),
            "to": int(candles[-1]["time"]),
            "split_time": int(candles[split]["time"]),
            "tape_cached": cached,
            "replay_seconds": round(replay_seconds, 1),
            "exit": active_plan.model_dump(),
        },
        "signals": {"fires": len(fires), "setups": len(setups)},
        "study": study(candles, setups, start=start, split=split, end=end, neutral=request.neutral),
        "trades": trades,
        "flags": report_flags(trades, tuned=request.tune),
    }
    if tuning is not None:
        report["tuning"] = tuning
    return report
```

4. Add the helper next to `report_flags`:

```python
def _setting(chosen: Dict[str, Any]):
    from backtest.tuning import Setting

    return Setting(chosen["filters"], chosen["stop_atr"], chosen["target_r"], chosen["max_bars"])
```

- [ ] **Step 4:** Run the whole backend suite → **425 passed**.
- [ ] **Step 5: Commit** `git add backend/backtest/runner.py backend/tests/test_backtest_runner.py && git commit -m "Tune on seen data, then verify the winner once on unseen" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 4: Client types and the tuned verdict

**Files:** Modify `frontend/lib/backtests.ts`, `frontend/tests/backtests.test.ts`

**Interfaces:** Produces `Grid`, `DEFAULT_GRID`, `TuningRow`, `TuningReport`; `BacktestReport.tuning?`, `.flags?`; `createBacktest(rule, { neutral, split, exit, tune, grid })`; `settingLabel(settings) -> string`; `overfit(report) -> boolean`; `tradeVerdict` prefixes `Selected from N settings: ` when tuned and appends the overfit note.

- [ ] **Step 1: Failing tests** (append; extend the import to include `overfit`, `settingLabel`, `type TuningReport`)

```ts
function tuning(over: Partial<TuningReport> = {}): TuningReport {
  const settings = { filters: {}, stop_atr: 1.5, target_r: 2, max_bars: 20 }
  return {
    tried: 27, objective: "expectancy in R per trade on seen data", min_trades: 30, qualified: true,
    chosen: settings,
    top: [{ settings, trades: 44, expectancy_r: 0.4, max_drawdown_pct: -8, total_return_pct: 15 }],
    ...over,
  }
}

describe("tuning", () => {
  it("labels a setting the way a trader would read it", () => {
    expect(settingLabel({ filters: {}, stop_atr: 1.5, target_r: 2, max_bars: 20 })).toBe("stop 1.5 ATR · target 2R · 20 bars")
    expect(settingLabel({ filters: { min_confidence: 70 }, stop_atr: 1, target_r: 3, max_bars: 10 })).toBe(
      "stop 1 ATR · target 3R · 10 bars · confidence 70",
    )
    expect(settingLabel({ filters: { min_strength: "strong" }, stop_atr: 2, target_r: 1, max_bars: 40 })).toBe(
      "stop 2 ATR · target 1R · 40 bars · strength strong",
    )
  })

  it("says a tuned verdict was selected from many tries, and flags a collapse", () => {
    const base = report(period())
    const tuned = { ...base, tuning: tuning(), flags: ["tuned", "likely_overfit"], trades: { seen: tp({ expectancy_r: 0.9 }), unseen: tp() } }
    expect(tradeVerdict(tuned)).toBe(
      "Selected from 27 settings: +0.35R per trade over 40 unseen trades, +12.50% total, worst drawdown -6.20% (seen: +0.90R per trade) — far below seen, so likely fitted to the seen data.",
    )
    expect(overfit(tuned)).toBe(true)
    expect(overfit({ ...base, trades: { seen: tp(), unseen: tp() } })).toBe(false)
  })
})
```

- [ ] **Step 2:** Run `npx vitest run tests/backtests.test.ts` → FAIL (missing exports).

- [ ] **Step 3: Implement.** In `frontend/lib/backtests.ts`:

1. Add to `BacktestReport`: `tuning?: TuningReport` and `flags?: string[]`.
2. `createBacktest` options type becomes `{ neutral: Neutral; split: number; exit: ExitPlan; tune: boolean; grid?: Grid }`, and the body gains `tune: options.tune,` and `grid: options.grid,`.
3. Replace `tradeVerdict` with the version below and append the rest:

```ts
export interface Grid {
  stop_atr: number[]
  target_r: number[]
  max_bars: number[]
  min_confidence: number[]
  min_strength: ("weak" | "medium" | "strong")[]
}

export const DEFAULT_GRID: Grid = {
  stop_atr: [1, 1.5, 2],
  target_r: [1, 2, 3],
  max_bars: [10, 20, 40],
  min_confidence: [60, 70, 80],
  min_strength: ["weak", "medium", "strong"],
}

export interface Setting {
  filters: { min_confidence?: number; min_strength?: string }
  stop_atr: number
  target_r: number
  max_bars: number
}

export interface TuningRow {
  settings: Setting
  trades: number
  expectancy_r: number | null
  max_drawdown_pct: number | null
  total_return_pct: number | null
}

export interface TuningReport {
  tried: number
  objective: string
  min_trades: number
  qualified: boolean
  chosen: Setting
  top: TuningRow[]
}

export function settingLabel(setting: Setting): string {
  const parts = [`stop ${setting.stop_atr} ATR`, `target ${setting.target_r}R`, `${setting.max_bars} bars`]
  if (setting.filters.min_confidence !== undefined) parts.push(`confidence ${setting.filters.min_confidence}`)
  if (setting.filters.min_strength !== undefined) parts.push(`strength ${setting.filters.min_strength}`)
  return parts.join(" · ")
}

export function overfit(report: BacktestReport): boolean {
  return (report.flags ?? []).includes("likely_overfit")
}

export function tradeVerdict(report: BacktestReport): string | null {
  if (!report.trades) return null
  const { seen, unseen } = report.trades
  if (unseen.trades === 0) return "No trades on unseen data."
  if (unseen.flags.includes("too_few_trades")) {
    return `Only ${unseen.trades} unseen trades — too few to judge this exit plan.`
  }
  const prefix = report.tuning ? `Selected from ${report.tuning.tried} settings: ` : "Trading it on unseen data: "
  const note = overfit(report) ? " — far below seen, so likely fitted to the seen data." : "."
  return (
    `${prefix}${fmtR(unseen.expectancy_r)} per trade over ${unseen.trades} unseen trades, ` +
    `${fmtPct(unseen.total_return_pct)} total, worst drawdown ${fmtPct(unseen.max_drawdown_pct)} ` +
    `(seen: ${fmtR(seen.expectancy_r)} per trade)${note}`
  )
}
```

Note the wording change: the untuned sentence now says "unseen trades" (the slice 3 test that asserted the old wording is updated in the same step — replace its expected string with `"Trading it on unseen data: +0.35R per trade over 40 unseen trades, +12.50% total, worst drawdown -6.20% (seen: +0.50R per trade)."`).

- [ ] **Step 4:** Run `npx vitest run` → **62 passed**.
- [ ] **Step 5: Commit** `git add frontend/lib/backtests.ts frontend/tests/backtests.test.ts && git commit -m "Client types for tuning, and a verdict that says how many settings were tried" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 5: Tuning in the sheet, and reopening a report

**Files:** Modify `frontend/components/backtest-sheet.tsx`

**Interfaces:** `BacktestSheet` gains an optional `jobId?: string` prop: when set, the sheet loads that job instead of showing the setup, so a finished report can be reopened. Setup gains a "Tune on seen data" toggle (**on** by default) with a one-line explanation; the report gains a tuning card (chosen setting, how many were tried, the top five on seen, and the "only the winner ran on unseen" note) and an overfit banner.

- [ ] **Step 1: Implement.** In `frontend/components/backtest-sheet.tsx`:

1. Extend the imports from `@/lib/backtests` with `DEFAULT_GRID`, `overfit`, `settingLabel`, `type TuningReport`.
2. Component props become:

```tsx
export default function BacktestSheet({
  rule,
  open,
  onOpenChange,
  jobId,
}: {
  rule: BacktestRule | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Reopen a finished or running backtest instead of setting up a new one. */
  jobId?: string
}) {
```

3. Add state `const [tune, setTune] = useState(true)` next to `split`, and after the reset effect add:

```tsx
  // Reopening: load the job this sheet was given.
  useEffect(() => {
    if (!open || !jobId) return
    let cancelled = false
    getBacktest(jobId)
      .then((loaded) => {
        if (!cancelled) setJob(loaded)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load that backtest")
      })
    return () => {
      cancelled = true
    }
  }, [open, jobId])
```

4. `createBacktest(rule, { neutral, split, exit: exitPlan })` becomes `createBacktest(rule, { neutral, split, exit: exitPlan, tune, grid: DEFAULT_GRID })`.
5. In the setup block, before the split buttons, add:

```tsx
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Tuning</span>
                <div className="flex gap-1.5">
                  <Button size="sm" variant={tune ? "default" : "outline"} className="h-7 flex-1 text-xs" onClick={() => setTune(true)}>
                    Tune on seen data
                  </Button>
                  <Button size="sm" variant={!tune ? "default" : "outline"} className="h-7 flex-1 text-xs" onClick={() => setTune(false)}>
                    Use my plan as is
                  </Button>
                </div>
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  {tune
                    ? "Tries a grid of stops, targets and holding times on the seen part of history, then runs only the best one on the unseen part. The report says how many were tried."
                    : "Runs the exit plan above on both periods, with nothing selected after the fact."}
                </p>
              </div>
```

6. Add the tuning card component above `BacktestSheet`:

```tsx
function TuningCard({ tuning }: { tuning: TuningReport }) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold text-foreground">Tuned on seen data</h3>
        <span className="font-mono text-[10px] text-muted-foreground">{tuning.tried} settings tried</span>
      </div>
      <p className="text-[11px] text-foreground">Best: {settingLabel(tuning.chosen)}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="text-muted-foreground">
            <tr className="text-left">
              <th className="py-1 pr-2 font-normal">Setting (seen)</th>
              <th className="py-1 pr-2 font-normal">Trades</th>
              <th className="py-1 pr-2 font-normal">Per trade</th>
              <th className="py-1 font-normal">Drawdown</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {tuning.top.map((row, i) => (
              <tr key={i} className="border-t border-border">
                <td className="py-1 pr-2 font-sans">{settingLabel(row.settings)}</td>
                <td className="py-1 pr-2">{row.trades}</td>
                <td className="py-1 pr-2">{fmtR(row.expectancy_r)}</td>
                <td className="py-1">{fmtPct(row.max_drawdown_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Ranked by {tuning.objective}, needing at least {tuning.min_trades} trades.
        {!tuning.qualified && " No setting reached that, so the one with the most trades was taken."} Only the chosen
        setting was run on unseen data — running the runners-up there would make unseen a second tuning set.
      </p>
    </section>
  )
}
```

7. In the report block, immediately after the verdict card, add:

```tsx
              {overfit(report) && (
                <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-500">
                  Unseen came in far below seen. That is what a setting fitted to the seen data looks like; treat the
                  unseen numbers as the honest ones.
                </p>
              )}
              {report.tuning && <TuningCard tuning={report.tuning} />}
```

8. Guard the setup so a reopened job never shows it: change `{supported && job === null && (` to `{supported && job === null && !jobId && (`.

- [ ] **Step 2: Verify** — `npx tsc --noEmit -p .` (only `tests/sw.test.ts`), `npx vitest run` (62), `npx next build` clean.
- [ ] **Step 3: Commit** `git add frontend/components/backtest-sheet.tsx && git commit -m "Tuning in the backtest sheet, with an overfit banner" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 6: Recent backtests in the Strategy panel

**Files:** Modify `frontend/lib/backtests.ts` (add `listBacktests`), `frontend/components/analysis-panel.tsx`

**Interfaces:** `listBacktests(): Promise<BacktestSummary[]>` where `BacktestSummary = Omit<Backtest, "report"> & { request?: { rule?: { name?: string; symbol?: string; timeframe?: string } } }`. The panel gains a fourth tab, **Tests**, listing the wallet's recent jobs (status, rule name, pair, when) with a click that reopens the report in the sheet.

- [ ] **Step 1: Add the client call** to `frontend/lib/backtests.ts`:

```ts
export interface BacktestSummary {
  id: string
  status: BacktestStatus
  progress: number
  created_at: string | null
  error: string | null
  request?: { rule?: { name?: string; symbol?: string; timeframe?: string } }
}

export async function listBacktests(): Promise<BacktestSummary[]> {
  const res = await fetch(`${API_BASE}/api/backtests`, { headers: authHeaders() })
  if (!res.ok) await failResponse(res, "Could not load your backtests")
  return res.json()
}
```

- [ ] **Step 2: The tab.** In `frontend/components/analysis-panel.tsx`:

1. Extend the `@/lib/backtests` import to `import { listBacktests, type BacktestRule, type BacktestSummary } from "@/lib/backtests"`.
2. Add state next to `backtestRule`:

```tsx
  const [backtestJobId, setBacktestJobId] = useState<string | undefined>(undefined)
  const [backtests, setBacktests] = useState<BacktestSummary[]>([])
```

3. Add a loader beside the existing refresh effects:

```tsx
  const refreshBacktests = useCallback(async () => {
    if (status !== "ready") return
    try {
      setBacktests(await listBacktests())
    } catch {
      // The tab simply stays empty; the sheet reports real failures.
    }
  }, [status])

  useEffect(() => {
    void refreshBacktests()
  }, [refreshBacktests])
```

4. Add the trigger next to the existing ones in `TabsList` (after the `fired` trigger):

```tsx
            <TabsTrigger value="tests" className="h-5 px-2 text-xs">
              Tests
            </TabsTrigger>
```

5. Add the tab body after the `fired` `TabsContent`:

```tsx
        {/* Tests: backtests this wallet has run, newest first. ------------- */}
        <TabsContent value="tests" className="mt-0 min-h-0 flex-1">
          {backtests.length === 0 ? (
            <div className="flex h-full items-center justify-center px-6 text-center">
              <p className="text-xs text-muted-foreground">
                No backtests yet. Run one from a rule with the Backtest button.
              </p>
            </div>
          ) : (
            <ScrollArea className="h-full">
              <div className="divide-y divide-border">
                {backtests.map((run) => (
                  <button
                    key={run.id}
                    type="button"
                    onClick={() => {
                      setBacktestJobId(run.id)
                      setBacktestRule({
                        name: run.request?.rule?.name ?? "Backtest",
                        symbol: run.request?.rule?.symbol ?? symbol,
                        timeframe: run.request?.rule?.timeframe ?? timeframe,
                        params: {},
                      })
                    }}
                    className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-secondary lg:px-4"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-xs font-medium text-foreground">
                          {run.request?.rule?.name ?? "Backtest"}
                        </span>
                        <span className="font-mono text-[10px] text-muted-foreground">
                          {run.request?.rule?.symbol} {run.request?.rule?.timeframe}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {run.status === "done"
                          ? `Finished ${run.created_at ? relativeTime(run.created_at) : ""}`
                          : run.status === "failed"
                            ? run.error ?? "Failed"
                            : `${run.status} · ${Math.round(run.progress * 100)}%`}
                      </p>
                    </div>
                    <Badge variant="secondary" className="h-4 px-1 text-[10px]">
                      {run.status}
                    </Badge>
                  </button>
                ))}
              </div>
            </ScrollArea>
          )}
        </TabsContent>
```

6. The Backtest button on a rule must clear any reopened id, and the sheet must receive the id:

```tsx
                      onClick={() => {
                        setBacktestJobId(undefined)
                        setBacktestRule(rule)
                      }}
```

```tsx
        <BacktestSheet
          rule={backtestRule}
          jobId={backtestJobId}
          open={backtestRule !== null}
          onOpenChange={(next) => {
            if (!next) {
              setBacktestRule(null)
              setBacktestJobId(undefined)
              void refreshBacktests()
            }
          }}
        />
```

- [ ] **Step 3: Verify** — `npx tsc --noEmit -p .`, `npx vitest run` (62), `npx next build` clean.
- [ ] **Step 4: Commit** `git add frontend/lib/backtests.ts frontend/components/analysis-panel.tsx && git commit -m "A Tests tab listing recent backtests to reopen" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 7: What a tuned number means (docs and spec)

**Files:** Modify `frontend/app/legal/risk/page.tsx`, `frontend/app/architecture/page.tsx`, `docs/superpowers/specs/2026-09-17-backtesting-design.md`

- [ ] **Step 1: Risk page.** Add a section after the existing pattern-reliability material (match the page's existing heading and paragraph markup):

> **Backtests are not forecasts.** A backtest replays stored candles through the same code that fires your alerts, and models entries, exits, fees and slippage. It cannot model the order book you would actually have traded into, funding, outages, or your own behaviour. Results on the *seen* period are selected: the platform searches many settings there and keeps the best, which flatters that number. The *unseen* period is measured once with that single choice, and it is the number worth reading. A large drop from seen to unseen is normal and is flagged; it means the settings fitted noise. Fewer than thirty trades tells you almost nothing either way.

- [ ] **Step 2: Architecture page.** After the backtesting paragraph added in slice 1/2 (or, if none, after the paragraph ending `<code>POST /api/scene</code>.`), add:

> Backtests run in their own container at a quarter of the API's CPU weight, so a replay can never delay a live alert. A replay walks each closed bar through the same matchers the alert engine uses, with only the bars up to that point in view, and records every candidate before filtering; that tape is cached, so tuning many filter and exit combinations costs seconds rather than a fresh replay each time. Tuning only ever sees history up to the seen/unseen boundary. The single setting it picks is then measured once on the unseen remainder, and the report always says how many settings were tried.

- [ ] **Step 3: Spec.** Under "6. Seen/unseen tuning" append `*(Slice 4 decisions:)*` with decisions 1–5 from this plan, and update the test-count sentence on the architecture page if it names one (it says `307 tests`; make it the current backend count).

- [ ] **Step 4: Verify** `npx next build`, then **Commit** `git add frontend/app/legal/risk/page.tsx frontend/app/architecture/page.tsx docs/superpowers/specs/2026-09-17-backtesting-design.md && git commit -m "Say plainly what a tuned backtest result is worth" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"`

---

### Task 8: Ship and verify

- [ ] **Step 1:** Backend suite 425, frontend 62, build clean; secret scan shows only plan text.
- [ ] **Step 2:** Push `feature/backtesting-slice4`, open PR "Backtesting slice 4: tuning on seen data", merge to main, push GitLab.
- [ ] **Step 3: Deploy.** If the GitHub deploy key is in place: `sudo git pull --ff-only`. Otherwise ship the commits as a bundle:
  ```bash
  git bundle create /tmp/slice4.bundle <previous-main>..main
  gcloud compute scp /tmp/slice4.bundle varun@tradesmart-backend:/tmp/slice4.bundle --zone asia-south1-a
  gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a --command 'cd /opt/tradesmart/app && sudo git fetch -q /tmp/slice4.bundle main && sudo git merge --ff-only -q FETCH_HEAD && rm -f /tmp/slice4.bundle && sudo docker compose -f docker-compose.prod.yml build -q backend backtester && sudo docker compose -f docker-compose.prod.yml up -d backend backtester && sleep 40 && sudo docker compose -f docker-compose.prod.yml ps --format "{{.Service}} {{.Status}}"'
  ```
- [ ] **Step 4: Real run.** With a throwaway session on the VM (token in a shell variable only), submit the BTCUSDT 1h doji rule with `"tune": true` and check: status reaches `tuning` then `done`; `tuning.tried == 27`; `tuning.top` is five rows sorted by expectancy; `meta.exit` equals `tuning.chosen`; `flags` contains `tuned`; the unseen trade count is non-zero. Submit the same rule with `"tune": false` and confirm no `tuning` section. Submit a 500-combination grid and expect **422**. Delete the jobs.
- [ ] **Step 5: Browser.** Signed in: run a tuned backtest from a rule; the sheet shows the tuning card with the settings tried and the chosen one, the overfit banner when flagged, and the Tests tab lists the run and reopens its report.
