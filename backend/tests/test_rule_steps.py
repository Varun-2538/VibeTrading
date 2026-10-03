"""The new sequence steps: what they accept, and what they refuse."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.sequence import describe_steps
from models.rule_schemas import STEP_TYPES, RuleCreate, SequenceRuleParams, step_warmup


def rule(steps, timeframe="1h", **kw):
    return RuleCreate(
        name="t", symbol="BTCUSDT", timeframe=timeframe,
        params={"agent": "sequence", "steps": steps, **kw},
    )


def test_the_mask_dispatch_knows_the_same_step_types():
    from analysis.sequence import MASK_STEPS

    assert MASK_STEPS == STEP_TYPES


def test_every_step_type_is_named():
    assert STEP_TYPES == (
        "candle", "indicator", "structure", "ema_cross", "macd_cross",
        "stoch_cross", "bollinger", "bollinger_squeeze", "vwap_cross",
        "volume_spike", "atr_expansion",
    )


def test_the_rsi_step_keeps_its_old_shape():
    # Rules already armed in production store exactly this.
    step = rule([{"type": "indicator", "indicator": "rsi", "period": 14, "cross": "above", "level": 30}]).params.steps[0]
    assert (step.indicator, step.period, step.cross, step.level) == ("rsi", 14, "above", 30.0)


def test_new_steps_take_their_defaults():
    steps = rule([
        {"type": "ema_cross"}, {"type": "macd_cross"}, {"type": "stoch_cross"},
        {"type": "bollinger"},
    ], lookback=400).params.steps
    assert (steps[0].fast, steps[0].slow, steps[0].cross) == (20, 50, "above")
    assert (steps[1].fast, steps[1].slow, steps[1].signal, steps[1].against) == (12, 26, 9, "signal")
    assert (steps[2].k, steps[2].k_smooth, steps[2].d, steps[2].against, steps[2].level) == (14, 3, 3, "d", 20.0)
    assert (steps[3].band, steps[3].cross, steps[3].period, steps[3].std) == ("upper", "above", 20, 2.0)


def test_a_fast_ema_must_be_faster_than_the_slow_one():
    with pytest.raises(ValidationError, match="faster"):
        rule([{"type": "ema_cross", "fast": 50, "slow": 20}])


def test_price_crossing_an_ema_is_a_fast_period_of_one():
    step = rule([{"type": "ema_cross", "fast": 1, "slow": 200}], lookback=500).params.steps[0]
    assert step.fast == 1


def test_warmup_is_the_longest_of_the_steps():
    assert step_warmup({"type": "candle", "shape": "doji"}) == 2
    assert step_warmup({"type": "indicator", "indicator": "rsi", "period": 14}) == 15
    assert step_warmup({"type": "ema_cross", "fast": 20, "slow": 50}) == 50
    assert step_warmup({"type": "macd_cross", "fast": 12, "slow": 26, "signal": 9}) == 35
    assert step_warmup({"type": "stoch_cross", "k": 14, "k_smooth": 3, "d": 3}) == 20
    assert step_warmup({"type": "bollinger_squeeze", "period": 20, "lookback": 120}) == 140
    assert step_warmup({"type": "volume_spike", "period": 20}) == 21
    assert step_warmup({"type": "atr_expansion", "period": 14}) == 16
    assert step_warmup({"type": "vwap_cross"}) == 2


def test_lookback_must_cover_the_longest_warmup():
    with pytest.raises(ValidationError, match="too short"):
        rule([{"type": "bollinger_squeeze"}], lookback=50)
    assert rule([{"type": "bollinger_squeeze"}], lookback=200).params.steps


def test_a_daily_vwap_rule_on_daily_candles_is_refused():
    with pytest.raises(ValidationError, match="week"):
        rule([{"type": "vwap_cross", "anchor": "day"}], timeframe="1d")
    assert rule([{"type": "vwap_cross", "anchor": "week"}], timeframe="1d").params.steps
    assert rule([{"type": "vwap_cross", "anchor": "day"}], timeframe="4h").params.steps


def test_steps_describe_themselves_in_words():
    said = describe_steps([
        {"type": "ema_cross", "fast": 20, "slow": 50, "cross": "above"},
        {"type": "macd_cross", "against": "zero", "cross": "below"},
        {"type": "stoch_cross", "against": "level", "level": 20, "cross": "above"},
        {"type": "bollinger", "band": "upper", "cross": "above"},
        {"type": "bollinger_squeeze", "lookback": 120},
        {"type": "vwap_cross", "anchor": "day", "cross": "above"},
        {"type": "volume_spike", "multiple": 2.0},
        {"type": "atr_expansion", "multiple": 2.0},
    ])
    assert said == (
        "EMA(20) crosses above EMA(50), then "
        "MACD crosses below zero, then "
        "stochastic %K crosses above 20, then "
        "close crosses above the upper Bollinger band, then "
        "Bollinger squeeze (tightest in 120 bars), then "
        "close crosses above the daily VWAP, then "
        "volume 2x its average, then "
        "range 2x ATR"
    )
