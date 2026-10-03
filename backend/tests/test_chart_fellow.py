"""
The chart fellow's guard: nothing reaches the chart that the scene cannot vouch for.

All model output here is canned. What is under test is that the schema and the
guard - not the model - decide what gets drawn.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.chart_fellow import FellowError, ground, parse_answer
from models.fellow_schemas import FellowAnswer

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
        "shapes": [{"shape": "doji", "t": T0 + 97 * H}],
    },
    "indicators": {
        "rsi": {"period": 14, "now": 48.0, "prev": 51.0,
                "recent_crosses": [{"level": 50, "dir": "below", "t": T0 + 98 * H}]},
        "ema": {"20": 60_900.0, "50": 60_400.0, "stack": "bullish"},
        "macd": {"line": 10.0, "signal": 8.0, "hist": 2.0},
    },
    "structure": {},
    "vocabulary": {},
    "unsupported": ["open_interest", "short_covering"],
}


def answer_with(marks, **finding):
    base = {"kind": "level", "label": "support", "present": True, "confidence": 80, "why": "six tests"}
    base.update(finding)
    base["marks"] = marks
    return json.dumps({"reply_md": "Yes.", "findings": [base], "not_visible": []})


# --- what the guard keeps --------------------------------------------------


def test_hline_at_a_scene_level_is_kept():
    a = parse_answer(answer_with([{"type": "hline", "price": 60_000.0, "label": "S"}]), SCENE)
    assert len(a.findings[0].marks) == 1
    assert a.findings[0].grounded is True


def test_hline_within_tolerance_is_kept():
    a = parse_answer(answer_with([{"type": "hline", "price": 60_020.0, "label": "S"}]), SCENE)
    assert len(a.findings[0].marks) == 1


def test_neckline_and_target_count_as_scene_prices():
    a = parse_answer(answer_with([
        {"type": "hline", "price": 61_900.0, "label": "neck"},
        {"type": "hline", "price": 63_950.0, "label": "target"},
    ]), SCENE)
    assert len(a.findings[0].marks) == 2


def test_bar_mark_on_a_scene_bar_is_kept():
    a = parse_answer(answer_with([{"type": "bar", "time": T0 + 97 * H, "text": "doji"}]), SCENE)
    assert len(a.findings[0].marks) == 1


def test_polyline_through_pattern_points_is_kept():
    pts = [{"time": T0 + 40 * H, "price": 59_800.0}, {"time": T0 + 55 * H, "price": 61_900.0},
           {"time": T0 + 70 * H, "price": 59_950.0}]
    a = parse_answer(answer_with([{"type": "polyline", "points": pts, "label": "W"}]), SCENE)
    assert len(a.findings[0].marks) == 1


# --- what the guard refuses ------------------------------------------------


def test_invented_level_is_dropped_and_flagged():
    """The model says there is support at 58,000. The detectors never found it."""
    a = parse_answer(answer_with([{"type": "hline", "price": 58_000.0, "label": "S"}]), SCENE)
    assert a.findings[0].marks == []
    assert a.findings[0].grounded is False
    assert "left off" in a.reply_md


def test_bar_mark_off_any_known_bar_is_dropped():
    a = parse_answer(answer_with([{"type": "bar", "time": T0 + 12 * H, "text": "?"}]), SCENE)
    assert a.findings[0].marks == []
    assert a.findings[0].grounded is False


def test_polyline_through_non_pattern_points_is_dropped():
    pts = [{"time": T0 + 40 * H, "price": 59_800.0}, {"time": T0 + 60 * H, "price": 62_000.0}]
    a = parse_answer(answer_with([{"type": "polyline", "points": pts, "label": "W"}]), SCENE)
    assert a.findings[0].marks == []


def test_box_outside_the_window_is_dropped():
    a = parse_answer(answer_with([{"type": "box", "from": T0 - 5 * H, "to": T0 + 10 * H,
                                   "price_top": 62_500.0, "price_bottom": 60_000.0}]), SCENE)
    assert a.findings[0].marks == []


def test_mixed_marks_keep_the_good_and_flag_the_finding():
    a = parse_answer(answer_with([
        {"type": "hline", "price": 60_000.0, "label": "real"},
        {"type": "hline", "price": 57_000.0, "label": "invented"},
    ]), SCENE)
    assert [m.label for m in a.findings[0].marks] == ["real"]
    assert a.findings[0].grounded is False


def test_the_claim_survives_even_when_its_marks_do_not():
    """The user still sees what the model said; they just do not see it drawn."""
    a = parse_answer(answer_with([{"type": "hline", "price": 1.0}], label="magic level"), SCENE)
    assert a.findings[0].label == "magic level"
    assert a.findings[0].present is True


# --- schema and parsing ----------------------------------------------------


def test_absent_findings_are_valid_answers():
    raw = json.dumps({"reply_md": "No W here.", "findings": [
        {"kind": "pattern", "label": "double bottom", "present": False, "confidence": 0, "why": "no pivots match"}],
        "not_visible": []})
    a = parse_answer(raw, SCENE)
    assert a.findings[0].present is False


def test_not_visible_carries_unsupported_asks():
    raw = json.dumps({"reply_md": "Can't see OI.", "findings": [], "not_visible": ["short_covering"]})
    assert parse_answer(raw, SCENE).not_visible == ["short_covering"]


def test_unknown_mark_type_is_rejected():
    with pytest.raises(FellowError):
        parse_answer(answer_with([{"type": "trendline", "price": 1}]), SCENE)


def test_unknown_finding_kind_is_rejected():
    with pytest.raises(FellowError):
        parse_answer(answer_with([], kind="vibes"), SCENE)


def test_code_fences_are_tolerated():
    raw = "```json\n" + json.dumps({"reply_md": "ok", "findings": [], "not_visible": []}) + "\n```"
    assert parse_answer(raw, SCENE).reply_md == "ok"


def test_garbage_is_a_friendly_error():
    with pytest.raises(FellowError, match="ask me again"):
        parse_answer("Sure! I see a lot going on here.", SCENE)


def test_ground_reports_how_many_were_dropped():
    a = FellowAnswer(reply_md="x", findings=[{
        "kind": "level", "label": "s", "present": True,
        "marks": [{"type": "hline", "price": 1.0}, {"type": "hline", "price": 2.0}, {"type": "hline", "price": 60_000.0}],
    }])
    _, dropped = ground(a, SCENE)
    assert dropped == 2
