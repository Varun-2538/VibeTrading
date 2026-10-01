"""Level detection over fixed candle fixtures - no I/O, no network."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.levels import adaptive_sensitivity, detect_levels, find_price_clusters


def candle(time, low, high, close=None):
    close = high if close is None else close
    return {
        "time": time,
        "open": (low + high) / 2,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1.0,
    }


def series(pairs, last_close):
    """Candles from (low, high) pairs, with the final close set explicitly."""
    candles = [candle(i * 60_000, lo, hi) for i, (lo, hi) in enumerate(pairs)]
    candles[-1]["close"] = last_close
    return candles


class TestFindPriceClusters:
    def test_groups_nearby_prices_and_counts_them(self):
        clusters = find_price_clusters([100.0, 100.5, 101.0, 200.0, 201.0], sensitivity=0.02)
        by_price = sorted(clusters, key=lambda c: c["price"])

        assert len(by_price) == 2
        assert by_price[0]["test_count"] == 3
        assert by_price[1]["test_count"] == 2

    def test_a_price_touched_once_is_not_a_level(self):
        assert find_price_clusters([100.0, 500.0], sensitivity=0.02) == []

    def test_empty_input(self):
        assert find_price_clusters([], sensitivity=0.02) == []


class TestDetectLevels:
    def test_support_below_spot_resistance_above(self):
        # Price oscillates in a band, then closes in the middle.
        pairs = [(90, 110)] * 10 + [(89, 111)] * 10
        result = detect_levels(series(pairs, last_close=100.0))

        assert result["support_levels"], "expected at least one support level"
        assert result["resistance_levels"], "expected at least one resistance level"

        for level in result["support_levels"]:
            assert level["price"] < 100.0
        for level in result["resistance_levels"]:
            assert level["price"] >= 100.0

    def test_a_broken_high_becomes_support(self):
        # A level repeatedly tested near 100, then price runs well above it.
        pairs = [(99, 101)] * 20 + [(148, 152)] * 6
        result = detect_levels(series(pairs, last_close=150.0))

        supports = [l["price"] for l in result["support_levels"]]
        assert any(95 <= p <= 105 for p in supports), (
            "the old ~100 high should now be support, not resistance"
        )
        assert all(l["price"] >= 150.0 for l in result["resistance_levels"])

    def test_strength_scales_with_share_not_raw_count(self):
        # Same level touched by every candle in both windows: always strong,
        # regardless of how many candles the window holds.
        short = detect_levels(series([(99, 101)] * 10, last_close=100.0))
        long = detect_levels(series([(99, 101)] * 200, last_close=100.0))

        assert short["support_levels"][0]["strength"] == "strong"
        assert long["support_levels"][0]["strength"] == "strong"

    def test_test_count_is_populated(self):
        result = detect_levels(series([(99, 101)] * 30, last_close=100.0))
        assert result["support_levels"][0]["test_count"] > 0

    def test_levels_are_nearest_first(self):
        pairs = [(70, 130)] * 4 + [(80, 120)] * 4 + [(95, 105)] * 4
        result = detect_levels(series(pairs, last_close=100.0))

        supports = [l["price"] for l in result["support_levels"]]
        assert supports == sorted(supports, reverse=True), (
            "supports should run from nearest spot downward"
        )

    @pytest.mark.parametrize("candles", [[], [candle(0, 99, 101)]])
    def test_degenerate_windows_return_empty_not_error(self, candles):
        result = detect_levels(candles)
        assert result["support_levels"] == []
        assert result["resistance_levels"] == []


class TestAdaptiveSensitivity:
    """
    Regression: a flat 2% tolerance made 1m charts useless. A thousand
    one-minute candles span a fraction of a percent, so every high and low
    collapsed into one band that sat entirely on one side of spot, and support
    always came back empty.
    """

    def test_tight_window_gets_a_tight_tolerance(self):
        # A 0.5%-tall window should not use a 2% tolerance.
        tolerance = adaptive_sensitivity([64_700.0], [64_400.0])
        assert tolerance < 0.02

    def test_tolerance_is_clamped_for_a_flat_window(self):
        tolerance = adaptive_sensitivity([100.0], [100.0])
        assert tolerance > 0, "a flat window must not collapse tolerance to zero"

    def test_tolerance_is_clamped_for_a_wild_window(self):
        assert adaptive_sensitivity([1000.0], [10.0]) <= 0.02

    def test_intraday_scale_window_yields_both_sides(self):
        # Roughly what 1m BTC looks like: a 0.5% range, price closing mid-band.
        pairs = []
        for i in range(200):
            base = 64_500 + (i % 20) * 15  # oscillates across ~0.45%
            pairs.append((base - 6, base + 6))
        result = detect_levels(series(pairs, last_close=64_640.0))

        assert result["support_levels"], "1m-scale window must produce support"
        assert result["resistance_levels"], "1m-scale window must produce resistance"
