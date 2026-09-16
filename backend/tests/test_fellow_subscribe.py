"""
Subscribing to what the fellow sees.

What is under test: the alert comes from the scene entry the finding points at,
is a rule the schema accepts, and is withheld whenever the finding is absent,
was corrected by the guard, or names something the rules engine cannot watch.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.chart_fellow import parse_answer
from agents.fellow_subscribe import attach_subscriptions, subscription_for
from models.fellow_schemas import Finding, PatternSettings
from models.rule_schemas import RuleCreate

T0 = 1_700_000_000_000
H = 3_600_000

SCENE = {
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "window": {"from": T0, "to": T0 + 99 * H, "bars": 100},
    "price": {"last": 61_000.0, "window_high": 63_000.0, "window_low": 59_000.0, "change_pct": 1.0},
    "levels": {
        "support": [{"price": 60_000.0, "strength": "strong", "tests": 6}],
        "resistance": [{"price": 62_500.0, "strength": "medium", "tests": 3}],
    },
    "patterns": [
        {
            "kind": "W", "state": "forming", "confidence": 71,
            "points": {
                "low1": {"t": T0 + 40 * H, "price": 59_800.0},
                "peak": {"t": T0 + 55 * H, "price": 61_900.0},
                "low2": {"t": T0 + 70 * H, "price": 59_950.0},
            },
            "neckline": 61_900.0, "target": 63_950.0,
        }
    ],
    "candles": {
        "last": [{"t": T0 + i * H, "o": 1, "h": 1, "l": 1, "c": 1} for i in range(95, 100)],
        "shapes": [
            {"shape": "bullish_engulfing", "t": T0 + 99 * H},
            {"shape": "doji", "t": T0 + 97 * H},
            {"shape": "inside_bar", "t": T0 + 97 * H},
        ],
    },
    "indicators": {
        "rsi": {"period": 14, "now": 48.0, "prev": 51.0,
                "recent_crosses": [{"level": 50, "dir": "below", "t": T0 + 98 * H}]},
        "ema": {"20": 60_900.0, "50": 60_400.0, "stack": "bullish",
                "recent_cross": {"dir": "bullish", "t": T0 + 96 * H}},
        "macd": {"line": 10.0, "signal": 8.0, "hist": 2.0},
    },
    "structure": {
        "trend": "up",
        "swings": [],
        "events": [{"event": "sweep", "side": "bullish", "level": 60_000.0, "t": T0 + 99 * H}],
        "pullback": None,
    },
    "vocabulary": {},
    "unsupported": ["open_interest"],
}


def finding(kind, label, marks=(), **extra):
    return Finding(kind=kind, label=label, present=True, confidence=70, marks=list(marks), **extra)


def assert_armable(sub):
    """Whatever we offer must be exactly what POST /api/rules accepts."""
    assert sub is not None
    RuleCreate(**sub.draft)


# --- one path per kind -------------------------------------------------------


def test_pattern_from_its_polyline():
    pts = SCENE["patterns"][0]["points"]
    mark = {"type": "polyline", "points": [
        {"time": pts[k]["t"], "price": pts[k]["price"]} for k in ("low1", "peak", "low2")
    ]}
    sub = subscription_for(finding("pattern", "that shape", [mark]), SCENE)
    assert_armable(sub)
    assert sub.draft["params"]["agent"] == "pattern"
    assert sub.draft["params"]["kinds"] == ["W"]
    assert sub.draft["params"]["states"] == ["confirmed"]
    # It watches for the kind, and says so.
    assert "any new one" in sub.summary


def test_pattern_carries_the_chart_detector_settings():
    settings = PatternSettings(strictness="strict", source="close", scale="swing")
    sub = subscription_for(finding("pattern", "double bottom"), SCENE, settings)
    assert_armable(sub)
    assert sub.draft["params"]["strictness"] == "strict"
    assert sub.draft["params"]["source"] == "close"


def test_pattern_label_must_name_a_pattern_the_scene_has():
    assert subscription_for(finding("pattern", "double top"), SCENE) is None
    assert subscription_for(finding("pattern", "cup and handle"), SCENE) is None


def test_inverse_head_and_shoulders_is_not_read_as_head_and_shoulders():
    scene = copy.deepcopy(SCENE)
    scene["patterns"][0]["kind"] = "IHS"
    sub = subscription_for(finding("pattern", "inverse head and shoulders"), scene)
    assert sub.draft["params"]["kinds"] == ["IHS"]
    assert subscription_for(finding("pattern", "head and shoulders"), scene) is None


def test_candle_from_its_bar_mark_uses_the_label_to_pick_between_shapes():
    mark = {"type": "bar", "time": T0 + 97 * H}
    sub = subscription_for(finding("candle", "inside bar", [mark]), SCENE)
    assert_armable(sub)
    assert sub.draft["params"] == {
        "agent": "sequence",
        "steps": [{"type": "candle", "shape": "inside_bar", "max_body_pct": sub.draft["params"]["steps"][0]["max_body_pct"]}],
        "within_bars": sub.draft["params"]["within_bars"],
        "lookback": sub.draft["params"]["lookback"],
    }
    # Sequences settle at close: no persistence wait.
    assert sub.draft["persist_bars"] == 0


def test_candle_from_label_alone():
    sub = subscription_for(finding("candle", "Bullish engulfing on the last bar"), SCENE)
    assert_armable(sub)
    assert sub.draft["params"]["steps"][0]["shape"] == "bullish_engulfing"
    assert subscription_for(finding("candle", "hammer"), SCENE) is None


def test_structure_sweep_from_its_level_line():
    sub = subscription_for(
        finding("structure", "sweep of support", [{"type": "hline", "price": 60_000.0}]), SCENE
    )
    assert_armable(sub)
    assert sub.draft["params"]["steps"] == [{"type": "structure", "event": "sweep", "side": "bullish"}]
    assert "liquidity sweep" in sub.summary


def test_structure_label_naming_a_different_event_does_not_borrow_the_sweep():
    mark = {"type": "bar", "time": T0 + 99 * H}
    assert subscription_for(finding("structure", "breakout", [mark]), SCENE) is None


def test_liquidity_grab_wording_finds_the_sweep():
    sub = subscription_for(finding("structure", "liquidity grab"), SCENE)
    assert sub.draft["params"]["steps"][0]["event"] == "sweep"


def test_pullback_from_label():
    scene = copy.deepcopy(SCENE)
    scene["structure"]["pullback"] = {
        "side": "bearish", "retrace": 0.5,
        "holds": {"label": "LH", "price": 62_000.0, "t": T0 + 90 * H},
    }
    sub = subscription_for(finding("structure", "pullback"), scene)
    assert sub.draft["params"]["steps"] == [{"type": "structure", "event": "pullback", "side": "bearish"}]


def test_trend_read_is_not_subscribable():
    assert subscription_for(finding("structure", "uptrend, higher lows"), SCENE) is None


def test_rsi_cross_from_its_bar():
    sub = subscription_for(finding("indicator", "RSI cross", [{"type": "bar", "time": T0 + 98 * H}]), SCENE)
    assert_armable(sub)
    assert sub.draft["params"]["steps"] == [
        {"type": "indicator", "indicator": "rsi", "period": 14, "cross": "below", "level": 50.0}
    ]


def test_ema_and_macd_crosses_have_no_rule_to_become():
    # The EMA cross bar is not an RSI cross bar, and the label is not about RSI.
    ema = finding("indicator", "EMA 20/50 cross", [{"type": "bar", "time": T0 + 96 * H}])
    assert subscription_for(ema, SCENE) is None
    assert subscription_for(finding("indicator", "MACD bullish cross"), SCENE) is None


def test_level_from_its_line_keeps_that_level_strength():
    sub = subscription_for(finding("level", "resistance", [{"type": "hline", "price": 62_500.0}]), SCENE)
    assert_armable(sub)
    assert sub.draft["params"] == {
        "agent": "liquidity", "side": "resistance", "min_strength": "medium",
        "event": "approach", "proximity_pct": 0.3, "lookback": 500,
    }


# --- refusals ----------------------------------------------------------------


def test_absent_findings_get_no_alert():
    f = Finding(kind="level", label="support", present=False)
    assert subscription_for(f, SCENE) is None


def test_findings_the_guard_corrected_get_no_alert():
    f = finding("level", "support", grounded=False)
    assert subscription_for(f, SCENE) is None


def test_scene_without_symbol_gets_no_alert():
    scene = dict(SCENE, symbol=None)
    assert subscription_for(finding("level", "support"), scene) is None


def test_invalid_detector_settings_are_withheld_not_raised():
    bad = PatternSettings(strictness="reckless")
    assert subscription_for(finding("pattern", "double bottom"), SCENE, bad) is None


# --- end to end through the guard ---------------------------------------------


def test_a_subscription_the_model_writes_is_replaced():
    raw = json.dumps({
        "reply_md": "Support at 60k, and a sweep.",
        "findings": [
            {"kind": "level", "label": "support", "present": True,
             "marks": [{"type": "hline", "price": 60_000.0}],
             "subscribe": {"summary": "free money", "draft": {"name": "x", "symbol": "ETHUSDT"}}},
            {"kind": "indicator", "label": "MACD", "present": True,
             "subscribe": {"summary": "invented", "draft": {}}},
        ],
    })
    answer = parse_answer(raw, SCENE)
    # The guard wiped both before anything else looked at them.
    assert all(f.subscribe is None for f in answer.findings)

    attach_subscriptions(answer, SCENE)
    level, macd = answer.findings
    assert level.subscribe.draft["symbol"] == "BTCUSDT"
    assert level.subscribe.summary != "free money"
    assert macd.subscribe is None


def test_serialised_answer_carries_the_draft():
    answer = parse_answer(json.dumps({
        "reply_md": "Doji two bars back.",
        "findings": [{"kind": "candle", "label": "doji", "present": True,
                      "marks": [{"type": "bar", "time": T0 + 97 * H}]}],
    }), SCENE)
    attach_subscriptions(answer, SCENE)
    dumped = answer.model_dump(by_alias=True)
    assert dumped["findings"][0]["subscribe"]["draft"]["params"]["steps"][0]["shape"] == "doji"
