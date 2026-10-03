"""
The scene: the assistant's entire view of the chart.

Pinned here: shape, caps, determinism, and a byte ceiling - because every byte
of the scene is a token spent on every question.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.scene import (
    LAST_BARS,
    MAX_LEVELS_PER_SIDE,
    MAX_PATTERNS,
    MAX_SHAPES,
    UNSUPPORTED,
    build_scene,
    empty_scene,
)

# Roughly 1,200 tokens. The system prompt, history and answer must fit
# beside it inside a few thousand tokens.
SCENE_BYTE_CEILING = 4_500


def random_walk(n=300, seed=3, start=60_000.0):
    rng = np.random.default_rng(seed)
    closes = start + np.cumsum(rng.normal(0, 120, n))
    out = []
    for i, c in enumerate(closes):
        o = c - rng.normal(0, 60)
        hi = max(o, c) + abs(rng.normal(0, 80))
        lo = min(o, c) - abs(rng.normal(0, 80))
        out.append({"time": 1_700_000_000_000 + i * 3_600_000, "open": o, "high": hi, "low": lo, "close": c, "volume": 1.0})
    return out


def test_empty_window_is_a_valid_scene():
    scene = build_scene([], symbol="btcusdt", timeframe="1h")
    assert scene == empty_scene("btcusdt", "1h")
    assert scene["symbol"] == "BTCUSDT"
    assert scene["window"]["bars"] == 0
    assert scene["price"] is None


def test_scene_has_every_section():
    scene = build_scene(random_walk(), symbol="BTCUSDT", timeframe="1h")
    for key in ("symbol", "timeframe", "window", "price", "levels", "patterns",
                "candles", "indicators", "structure", "vocabulary", "unsupported"):
        assert key in scene, key
    assert scene["window"]["bars"] == 300
    assert set(scene["levels"]) == {"support", "resistance"}
    assert "rsi" in scene["indicators"]
    assert scene["indicators"]["ema"]["stack"] in ("bullish", "bearish")


def test_unsupported_concepts_are_named():
    scene = build_scene(random_walk(), symbol="BTCUSDT", timeframe="1h")
    assert "short_covering" in scene["unsupported"]
    assert "open_interest" in scene["unsupported"]
    assert list(UNSUPPORTED) == scene["unsupported"]


def test_scene_is_deterministic():
    """Same candles, byte-identical JSON: the guard depends on it."""
    a = build_scene(random_walk(), symbol="BTCUSDT", timeframe="1h")
    b = build_scene(random_walk(), symbol="BTCUSDT", timeframe="1h")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_caps_hold_on_a_long_noisy_window():
    scene = build_scene(random_walk(n=1000, seed=11), symbol="BTCUSDT", timeframe="1h")
    assert len(scene["levels"]["support"]) <= MAX_LEVELS_PER_SIDE
    assert len(scene["levels"]["resistance"]) <= MAX_LEVELS_PER_SIDE
    assert len(scene["patterns"]) <= MAX_PATTERNS
    assert len(scene["candles"]["shapes"]) <= MAX_SHAPES
    assert len(scene["candles"]["last"]) == LAST_BARS


def test_scene_stays_under_the_byte_ceiling():
    scene = build_scene(random_walk(n=1000, seed=11), symbol="BTCUSDT", timeframe="1h")
    size = len(json.dumps(scene, separators=(",", ":")))
    assert size <= SCENE_BYTE_CEILING, size


def test_window_bounds_come_from_the_candles_given():
    bars = random_walk(n=50)
    scene = build_scene(bars, symbol="BTCUSDT", timeframe="1h")
    assert scene["window"]["from"] == bars[0]["time"]
    assert scene["window"]["to"] == bars[-1]["time"]


def test_shapes_are_newest_first():
    bars = random_walk(n=120, seed=5)
    # Force three dojis at known bars.
    for i in (10, 60, 110):
        bars[i]["open"] = bars[i]["close"] - 0.01
        bars[i]["high"] = bars[i]["close"] + 200
        bars[i]["low"] = bars[i]["close"] - 200
    scene = build_scene(bars, symbol="BTCUSDT", timeframe="1h")
    times = [s["t"] for s in scene["candles"]["shapes"] if s["shape"] == "doji"]
    assert times == sorted(times, reverse=True)
    assert bars[110]["time"] in times


def test_prices_are_rounded_to_the_symbol_scale():
    scene = build_scene(random_walk(start=0.5), symbol="DOGEUSDT", timeframe="1h")
    assert len(str(scene["price"]["last"]).split(".")[-1]) <= 5
    scene = build_scene(random_walk(start=60_000), symbol="BTCUSDT", timeframe="1h")
    assert len(str(scene["price"]["last"]).split(".")[-1]) <= 1
