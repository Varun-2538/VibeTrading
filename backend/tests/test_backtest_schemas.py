"""What a backtest request may be."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.backtest_schemas import (
    BACKTEST_TIMEFRAMES,
    MIN_EVALUATED_BARS,
    BacktestCreate,
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
