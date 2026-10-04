"""What a backtest request may be."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.backtest_schemas import (
    BACKTEST_TIMEFRAMES,
    MIN_EVALUATED_BARS,
    POOL_FEE_TIERS,
    BacktestCreate,
    ExitPlan,
    required_bars,
    window_size,
)

RULE = {
    "name": "doji", "symbol": "btcusdt", "timeframe": "1h",
    "params": {"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}]},
}


def test_defaults():
    body = BacktestCreate(rule=RULE)
    assert body.neutral == "skip" and body.split == 0.7
    assert body.rule.params.lookback == 300


def test_window_matches_the_live_sweep():
    assert window_size(300) == 299
    assert required_bars(300) == 299 + MIN_EVALUATED_BARS


def test_timeframes_are_the_ones_with_history():
    assert BACKTEST_TIMEFRAMES == ("5m", "15m", "1h", "1d")
    with pytest.raises(ValidationError, match="5m, 15m, 1h or 1d"):
        BacktestCreate(rule={**RULE, "timeframe": "1m"})


@pytest.mark.parametrize("split", [0.4, 0.95])
def test_split_is_bounded(split):
    with pytest.raises(ValidationError):
        BacktestCreate(rule=RULE, split=split)


def test_an_invalid_rule_is_rejected_by_the_rule_schema():
    with pytest.raises(ValidationError):
        BacktestCreate(rule={**RULE, "params": {"agent": "sequence", "steps": []}})


def test_exit_plan_defaults_and_needs_a_stop():
    body = BacktestCreate(rule=RULE)
    assert (body.exit.stop_atr, body.exit.target_r, body.exit.max_bars, body.exit.fee_pct) == (1.5, 2.0, 20, 0.05)
    assert (body.exit.slippage_pct, body.exit.risk_pct, body.exit.exit_on_opposite) == (0.02, 1.0, False)
    # The default pool is the majors' 0.05% tier, and gas is nobody's to guess.
    assert body.exit.fee_pct in POOL_FEE_TIERS
    assert (body.exit.gas_usd, body.exit.trade_usd, body.exit.gas_pct) == (0.0, 1000.0, 0.0)
    assert ExitPlan(fee_pct=0.3, gas_usd=1, trade_usd=500).swap_cost_pct == pytest.approx(0.5)
    with pytest.raises(ValidationError, match="needs a stop"):
        BacktestCreate(rule=RULE, exit={"stop_atr": None})


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


def test_sides_defaults_to_both_and_only_accepts_a_venue_it_knows():
    """A spot pool has no short, so long-only has to be expressible - and typed."""
    assert BacktestCreate(rule=RULE).sides == "both"
    assert BacktestCreate(rule=RULE, sides="long").sides == "long"
    with pytest.raises(ValidationError):
        BacktestCreate(rule=RULE, sides="long_only")
