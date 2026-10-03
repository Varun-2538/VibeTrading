"""
Head and shoulders, inverse, and cup and handle, on line-segment fixtures.

Same approach as test_patterns: the geometry is built from ramps so every
assertion is about a known price, and a random walk is measured for how many
of these shapes it contains - because it contains some, and pretending
otherwise would be the wrong lesson to teach the risk page.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis.patterns_big import BIG_KINDS, detect_big_patterns
from test_patterns import ramp, to_candles

LEG = 8  # bars per leg; pivots need k=4 bars either side


def preamble():
    """Something with range before the pattern, so ATR is not tiny."""
    return ramp(100, 96, LEG) + ramp(96, 104, LEG) + ramp(104, 100, LEG)


def hs_series(tail=None, shoulder=110.0, head=120.0, neck=100.0):
    """
    Up to the left shoulder, down to the neckline, up to the head, down to
    the neckline, up to the right shoulder, then `tail` (default: partway
    back toward the neckline, so the pattern is forming).
    """
    p = preamble()
    p += ramp(p[-1], shoulder, LEG) + ramp(shoulder, neck, LEG)
    p += ramp(neck, head, LEG) + ramp(head, neck, LEG)
    p += ramp(neck, shoulder, LEG)
    p += tail if tail is not None else ramp(shoulder, 106, LEG // 2)
    return to_candles(p)


def ihs_series(tail=None):
    """
    Three lows - shoulder 110, head 100, shoulder 110 - with the neckline
    highs at 120 between them, then `tail` (default: rising off the right
    shoulder, so the pattern is forming).
    """
    p = preamble()
    p += ramp(p[-1], 120, LEG) + ramp(120, 110, LEG)
    p += ramp(110, 120, LEG) + ramp(120, 100, LEG)
    p += ramp(100, 120, LEG) + ramp(120, 110, LEG)
    p += tail if tail is not None else ramp(110, 114, LEG // 2)
    return to_candles(p)


def cup_series(handle_low=112.0, tail=None, bars=40):
    """
    A parabolic bowl from rim 120 down to 100 and back, a handle that dips to
    `handle_low`, then `tail`.
    """
    p = preamble() + ramp(100, 120, LEG)
    x = np.linspace(-1, 1, bars)
    bowl = list(120 - 20 * (1 - x * x))  # 120 at both rims, 100 at the middle
    p += bowl
    p += ramp(120, handle_low, LEG // 2 + 1)
    p += tail if tail is not None else ramp(handle_low, 115, LEG // 2)
    return to_candles(p)


def kinds_found(candles, **kw):
    return [p["kind"] for p in detect_big_patterns(candles, **kw)]


# --- head and shoulders --------------------------------------------------------


def test_head_and_shoulders_is_found_forming():
    found = detect_big_patterns(hs_series(), strictness="balanced")
    hs = [p for p in found if p["kind"] == "HS"]
    assert hs, kinds_found(hs_series())
    p = hs[0]
    assert p["state"] == "forming"
    assert p["points"]["head"]["price"] == pytest.approx(120.0)
    assert p["neckline"] == pytest.approx(100.0, abs=0.5)
    assert p["target"] == pytest.approx(80.0, abs=1.0)
    assert set(p["points"]) == {"shoulder1", "trough1", "head", "trough2", "shoulder2"}


def test_head_and_shoulders_confirms_on_a_close_below_the_neckline():
    tail = ramp(110, 97, LEG)
    found = [p for p in detect_big_patterns(hs_series(tail=tail)) if p["kind"] == "HS"]
    assert found and found[0]["state"] == "confirmed"


def test_head_and_shoulders_approaches_near_the_neckline():
    tail = ramp(110, 102, LEG)
    found = [p for p in detect_big_patterns(hs_series(tail=tail)) if p["kind"] == "HS"]
    assert found and found[0]["state"] == "approaching"


def test_no_pattern_until_price_turns_off_the_right_shoulder():
    tail = ramp(110, 113, LEG // 2)  # still rising
    assert "HS" not in kinds_found(hs_series(tail=tail))


def test_head_must_stand_clear_of_the_shoulders():
    """Three roughly equal peaks are a range, not a head and shoulders."""
    assert "HS" not in kinds_found(hs_series(head=111.0))


def test_shoulders_must_match():
    p = preamble()
    p += ramp(p[-1], 105, LEG) + ramp(105, 100, LEG) + ramp(100, 120, LEG)
    p += ramp(120, 100, LEG) + ramp(100, 115, LEG) + ramp(115, 108, LEG // 2)
    assert "HS" not in kinds_found(to_candles(p), strictness="strict")


def test_inverse_is_the_mirror():
    found = [p for p in detect_big_patterns(ihs_series()) if p["kind"] == "IHS"]
    assert found, kinds_found(ihs_series())
    p = found[0]
    assert p["state"] == "forming"
    assert p["points"]["head"]["price"] == pytest.approx(100.0)
    assert p["target"] > p["neckline"]


def test_inverse_confirms_on_a_close_above_the_neckline():
    tail = ramp(110, 123, LEG)
    found = [p for p in detect_big_patterns(ihs_series(tail=tail)) if p["kind"] == "IHS"]
    assert found and found[0]["state"] == "confirmed"


# --- cup and handle ------------------------------------------------------------


def test_cup_and_handle_is_found_forming():
    found = [p for p in detect_big_patterns(cup_series()) if p["kind"] == "CUP"]
    assert found, kinds_found(cup_series())
    p = found[0]
    assert p["state"] == "forming"
    assert p["points"]["bottom"]["price"] == pytest.approx(100.0, abs=0.6)
    assert p["neckline"] == pytest.approx(120.0, abs=0.5)
    assert p["target"] == pytest.approx(140.0, abs=1.0)
    assert set(p["points"]) == {"left_rim", "bottom", "right_rim", "handle"}


def test_cup_confirms_on_a_close_above_the_rim():
    tail = ramp(112, 123, LEG)
    found = [p for p in detect_big_patterns(cup_series(tail=tail)) if p["kind"] == "CUP"]
    assert found and found[0]["state"] == "confirmed"


def test_a_deep_handle_is_not_a_handle():
    """Giving back more than half the cup is a new leg down, not a handle."""
    assert "CUP" not in kinds_found(cup_series(handle_low=104.0))


def test_a_v_bottom_is_not_a_cup():
    p = preamble() + ramp(100, 120, LEG)
    p += ramp(120, 100, 20) + ramp(100, 120, 20)  # straight down, straight up
    p += ramp(120, 112, LEG // 2 + 1) + ramp(112, 115, LEG // 2)
    assert "CUP" not in kinds_found(to_candles(p))


# --- contract ------------------------------------------------------------------


def test_returns_the_same_shape_as_the_double_pattern_detector():
    p = detect_big_patterns(hs_series())[0]
    for key in ("kind", "state", "confidence", "components", "points", "neckline", "target"):
        assert key in p
    assert all({"time", "price", "index"} <= set(pt) for pt in p["points"].values())
    assert 0 <= p["confidence"] <= 100


def test_unknown_kind_and_strictness_are_errors():
    with pytest.raises(ValueError):
        detect_big_patterns(hs_series(), kinds=("W",))
    with pytest.raises(ValueError):
        detect_big_patterns(hs_series(), strictness="sloppy")


def test_short_or_flat_windows_yield_nothing():
    assert detect_big_patterns(to_candles([100.0] * 60)) == []
    assert detect_big_patterns(to_candles(ramp(100, 110, 10))) == []


def test_random_walk_rate_is_measured_not_hidden():
    """
    These shapes exist in noise. The number is pinned so a change in the
    detector that doubles it is noticed, and so the risk page's claim stays
    true. Measured: one to five per thousand random bars across seeds, an
    order of magnitude fewer than W/M, and no cups at all - the bowl test is
    what keeps them out.
    """
    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0, 1, 1000))
    found = detect_big_patterns(to_candles(list(closes)), max_results=None)
    assert len(found) <= 10, f"{len(found)} big patterns in 1000 random bars"
    assert not [p for p in found if p["kind"] == "CUP"]
