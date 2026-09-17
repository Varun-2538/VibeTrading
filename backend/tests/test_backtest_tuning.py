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
