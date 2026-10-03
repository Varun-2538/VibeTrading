"""
The parser's validation, with canned model output. No LLM in the loop: what is
under test is that the rule schema, not the model, decides what gets drafted.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.rule_parser import RuleParseError, describe_draft, parse_draft

GOOD = {
    "name": "BTC doji + RSI",
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "params": {
        "agent": "sequence",
        "steps": [
            {"type": "candle", "shape": "doji"},
            {"type": "indicator", "indicator": "rsi", "period": 14, "cross": "above", "level": 30},
        ],
        "within_bars": 3,
    },
}


def test_well_formed_output_becomes_a_rule():
    rule = parse_draft(json.dumps(GOOD), "ETHUSDT", "4h")
    assert rule.symbol == "BTCUSDT"
    assert rule.params.agent == "sequence"
    assert rule.resolved_persist_bars() == 0


def test_code_fences_are_tolerated():
    rule = parse_draft(f"```json\n{json.dumps(GOOD)}\n```", None, "1h")
    assert rule.name == "BTC doji + RSI"


def test_defaults_fill_missing_symbol_and_timeframe():
    data = {k: v for k, v in GOOD.items() if k not in ("symbol", "timeframe")}
    rule = parse_draft(json.dumps(data), "SOLUSDT", "15m")
    assert (rule.symbol, rule.timeframe) == ("SOLUSDT", "15m")


def test_missing_name_is_derived_from_the_steps():
    data = {k: v for k, v in GOOD.items() if k != "name"}
    rule = parse_draft(json.dumps(data), None, "1h")
    assert rule.name == "BTCUSDT doji, then RSI(14) crosses above 30"


def test_model_declared_error_is_surfaced_verbatim():
    with pytest.raises(RuleParseError, match="MACD is not supported"):
        parse_draft('{"error": "MACD is not supported yet"}', "BTCUSDT", "1h")


def test_hallucinated_indicator_is_rejected_by_the_schema():
    data = json.loads(json.dumps(GOOD))
    data["params"]["steps"][1]["indicator"] = "stochastic"
    with pytest.raises(RuleParseError, match="indicator"):
        parse_draft(json.dumps(data), None, "1h")


def test_impossible_level_is_rejected():
    data = json.loads(json.dumps(GOOD))
    data["params"]["steps"][1]["level"] = 130
    with pytest.raises(RuleParseError, match="level"):
        parse_draft(json.dumps(data), None, "1h")


def test_no_symbol_anywhere_asks_for_one():
    data = {k: v for k, v in GOOD.items() if k != "symbol"}
    with pytest.raises(RuleParseError, match="Which pair"):
        parse_draft(json.dumps(data), None, "1h")


def test_garbage_is_a_friendly_error():
    with pytest.raises(RuleParseError, match="couldn't read"):
        parse_draft("Sure! Here is your rule:", "BTCUSDT", "1h")


def test_every_shape_the_detectors_know_is_accepted():
    from analysis.candles import SHAPES

    for shape in SHAPES:
        data = json.loads(json.dumps(GOOD))
        data["params"]["steps"] = [{"type": "candle", "shape": shape}]
        assert parse_draft(json.dumps(data), None, "1h").params.steps[0].shape == shape


def test_the_prompt_names_every_shape():
    from agents.rule_parser import SYSTEM_PROMPT
    from analysis.candles import SHAPES

    for shape in SHAPES:
        assert shape in SYSTEM_PROMPT


def test_structure_steps_are_accepted_and_described():
    data = json.loads(json.dumps(GOOD))
    data["params"]["steps"] = [
        {"type": "structure", "event": "sweep", "side": "bullish"},
        {"type": "candle", "shape": "bullish_engulfing"},
    ]
    rule = parse_draft(json.dumps(data), None, "1h")
    assert rule.params.steps[0].type == "structure"
    from analysis.sequence import describe_steps
    assert describe_steps(rule.params.model_dump()["steps"]) == "bullish sweep, then bullish_engulfing"


def test_unknown_structure_event_is_rejected():
    data = json.loads(json.dumps(GOOD))
    data["params"]["steps"] = [{"type": "structure", "event": "order_block", "side": "bullish"}]
    with pytest.raises(RuleParseError, match="event"):
        parse_draft(json.dumps(data), None, "1h")


def test_pattern_form_is_accepted_and_named():
    data = {"symbol": "BTCUSDT", "timeframe": "4h",
            "params": {"agent": "pattern", "kinds": ["HS", "IHS"], "states": ["confirmed"], "min_confidence": 65}}
    rule = parse_draft(json.dumps(data), None, "1h")
    assert rule.params.agent == "pattern"
    assert rule.params.kinds == ["HS", "IHS"]
    assert rule.resolved_persist_bars() == 1  # patterns can repaint; keep the wait
    assert rule.name == "BTCUSDT HS/IHS confirmed"


def test_pattern_form_agent_is_inferred_from_kinds():
    data = {"symbol": "ETHUSDT", "params": {"kinds": ["CUP"]}}
    assert parse_draft(json.dumps(data), None, "1h").params.agent == "pattern"


def test_unknown_pattern_kind_is_rejected():
    data = {"symbol": "ETHUSDT", "params": {"agent": "pattern", "kinds": ["WEDGE"]}}
    with pytest.raises(RuleParseError, match="kinds"):
        parse_draft(json.dumps(data), None, "1h")


def test_describe_draft_covers_both_forms():
    """The chat card once assumed every draft had steps; a pattern draft 500ed in production."""
    from agents.rule_parser import describe_draft

    seq = parse_draft(json.dumps(GOOD), None, "1h")
    assert describe_draft(seq) == "doji, then RSI(14) crosses above 30, each step within 3 bars of the last"

    pat = parse_draft(json.dumps({"symbol": "ETHUSDT", "params": {"kinds": ["IHS"], "min_confidence": 60}}), None, "4h")
    assert describe_draft(pat) == "inverse head and shoulders confirmed, confidence at least 60%"


def test_a_draft_may_use_the_new_indicator_steps():
    raw = json.dumps({
        "name": "MACD cross", "symbol": "ETHUSDT", "timeframe": "15m",
        "params": {"agent": "sequence", "within_bars": 3, "lookback": 300,
                   "steps": [{"type": "macd_cross", "against": "signal", "cross": "above"}]},
    })
    draft = parse_draft(raw, "BTCUSDT", "1h")
    assert draft.params.agent == "sequence"
    assert draft.params.steps[0].type == "macd_cross"
    assert "MACD crosses above its signal line" in describe_draft(draft)


def test_a_draft_chaining_a_squeeze_and_a_breakout_is_valid():
    raw = json.dumps({
        "name": "squeeze break", "symbol": "BTCUSDT", "timeframe": "1h",
        "params": {"agent": "sequence", "within_bars": 5, "lookback": 400,
                   "steps": [{"type": "bollinger_squeeze"},
                             {"type": "bollinger", "band": "upper", "cross": "above"}]},
    })
    draft = parse_draft(raw, "BTCUSDT", "1h")
    assert [s.type for s in draft.params.steps] == ["bollinger_squeeze", "bollinger"]


def test_the_prompt_teaches_every_step_type():
    from agents.rule_parser import SYSTEM_PROMPT
    from models.rule_schemas import STEP_TYPES

    for kind in STEP_TYPES:
        assert kind in SYSTEM_PROMPT, kind
    for word in ("VWAP", "squeeze", "volume", "stochastic", "MACD", "EMA"):
        assert word.lower() in SYSTEM_PROMPT.lower(), word
