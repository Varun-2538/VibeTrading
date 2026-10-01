"""
W/M detection over synthetic fixtures.

The fixtures are built from line segments so every pattern's geometry is known
exactly, which is what lets these tests assert on prices rather than just on
"something was found".
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.patterns import atr, detect_double_patterns, find_pivots


def ramp(start, end, bars):
    """Prices walking linearly from start to end over `bars` candles."""
    if bars <= 0:
        return []
    step = (end - start) / bars
    return [start + step * (i + 1) for i in range(bars)]


def to_candles(prices, wick=0.0):
    """Candles from a close series, with optional symmetric wicks."""
    candles = []
    for i, price in enumerate(prices):
        prev = prices[i - 1] if i else price
        candles.append(
            {
                "time": (1_700_000_000 + i * 60) * 1000,
                "open": prev,
                "high": max(prev, price) + wick,
                "low": min(prev, price) - wick,
                "close": price,
                "volume": 1.0,
            }
        )
    return candles


def w_series(
    *,
    base=100.0,
    depth=10.0,
    low2_offset=0.0,
    leg=20,
    tail=0,
    scale=1.0,
    wick=0.0,
):
    """
    A textbook W: down to low1, up to the neckline peak, down to low2, back up.

    `tail` is how far past the second low the series runs, which is what moves
    the pattern between forming, approaching and confirmed.
    `scale` multiplies every price so the same shape can be tested at 1m-sized
    and 1d-sized magnitudes.
    `wick` inflates each candle's range without changing its close, which
    raises ATR independently of the pattern's height. That is the only way to
    express a genuinely shallow pattern: on a smooth ramp the true range is
    nearly zero, so even a tiny W measures as many ATR deep.
    """
    peak = base
    low1 = base - depth
    low2 = low1 + low2_offset

    prices = [base + depth * 0.5]
    prices += ramp(prices[-1], low1, leg)
    prices += ramp(low1, peak, leg)
    prices += ramp(peak, low2, leg)
    if tail:
        prices += ramp(low2, low2 + tail, leg)
    return to_candles([p * scale for p in prices], wick=wick * scale)


def m_series(**kwargs):
    """The mirror image of w_series, so a double top should be found."""
    candles = w_series(**kwargs)
    mid = 200.0 * kwargs.get("scale", 1.0)
    flipped = []
    for c in candles:
        flipped.append(
            {
                "time": c["time"],
                "open": mid - c["open"],
                "high": mid - c["low"],
                "low": mid - c["high"],
                "close": mid - c["close"],
                "volume": c["volume"],
            }
        )
    return flipped


def noise_series(bars=200):
    """A sawtooth too shallow and too regular to be a pattern."""
    prices = [100.0 + (i % 4) * 0.05 for i in range(bars)]
    return to_candles(prices)


class TestAtr:
    def test_flat_series_has_zero_range(self):
        assert atr(to_candles([100.0] * 50)) == 0.0

    def test_moving_series_has_positive_range(self):
        assert atr(to_candles(ramp(100, 200, 50))) > 0

    def test_scales_with_price_magnitude(self):
        small = atr(to_candles(ramp(100, 110, 50)))
        large = atr(to_candles(ramp(1000, 1100, 50)))
        assert large > small * 5


class TestFindPivots:
    def test_finds_the_trough_of_a_v(self):
        candles = to_candles(ramp(100, 90, 15) + ramp(90, 100, 15))
        lows, _ = find_pivots(candles, k=4)
        assert lows, "expected a pivot low at the bottom of the V"
        trough = min(lows, key=lambda i: candles[i]["close"])
        assert candles[trough]["close"] == pytest.approx(90, abs=1.0)

    def test_finds_the_crest_of_an_inverted_v(self):
        candles = to_candles(ramp(100, 110, 15) + ramp(110, 100, 15))
        _, highs = find_pivots(candles, k=4)
        assert highs
        crest = max(highs, key=lambda i: candles[i]["close"])
        assert candles[crest]["close"] == pytest.approx(110, abs=1.0)

    def test_no_pivots_in_a_monotonic_ramp(self):
        lows, highs = find_pivots(to_candles(ramp(100, 200, 60)), k=4)
        assert lows == [] and highs == []


class TestDetectW:
    def test_finds_a_textbook_double_bottom(self):
        patterns = detect_double_patterns(w_series(tail=12), kinds=("W",))
        assert patterns, "expected a W"

        w = patterns[0]
        assert w["kind"] == "W"
        assert w["points"]["low1"]["price"] == pytest.approx(90, abs=1.5)
        assert w["points"]["low2"]["price"] == pytest.approx(90, abs=1.5)
        assert w["neckline"] == pytest.approx(100, abs=1.5)

    def test_target_is_a_measured_move_above_the_neckline(self):
        w = detect_double_patterns(w_series(tail=12), kinds=("W",))[0]
        height = w["neckline"] - min(
            w["points"]["low1"]["price"], w["points"]["low2"]["price"]
        )
        assert w["target"] == pytest.approx(w["neckline"] + height, abs=0.5)

    def test_mismatched_lows_are_rejected(self):
        # Second low far below the first: not a double bottom.
        patterns = detect_double_patterns(
            w_series(low2_offset=-8.0, tail=12), kinds=("W",)
        )
        assert patterns == []

    def test_shallow_wobble_is_rejected(self):
        # Shallow means shallow against the noise, not small in absolute price.
        # Wide candle ranges around a 1-unit W leave the pattern well under the
        # depth threshold, so it is a wobble rather than a double bottom.
        patterns = detect_double_patterns(
            w_series(depth=1.0, tail=0.5, wick=5.0), kinds=("W",)
        )
        assert patterns == []

    def test_the_same_shape_is_accepted_when_the_noise_is_small(self):
        # The companion to the test above: identical geometry, quiet candles.
        patterns = detect_double_patterns(
            w_series(depth=1.0, tail=1.2, wick=0.02), kinds=("W",)
        )
        assert patterns, "a clean W should survive regardless of its absolute size"

    def test_noise_produces_nothing(self):
        assert detect_double_patterns(noise_series(), kinds=("W",)) == []

    def test_confidence_decomposes_into_its_components(self):
        w = detect_double_patterns(w_series(tail=12), kinds=("W",))[0]
        assert 0 <= w["confidence"] <= 100
        for term in ("similarity", "depth", "symmetry"):
            assert 0 <= w["components"][term] <= 100

    def test_matched_lows_score_higher_than_mismatched(self):
        clean = detect_double_patterns(w_series(tail=12), kinds=("W",))[0]
        # Offset stays inside the balanced tolerance (0.5 ATR) so the pattern
        # is still found - the point is that it scores lower, not that it is
        # rejected.
        rough = detect_double_patterns(
            w_series(low2_offset=0.15, tail=12), kinds=("W",)
        )
        assert rough, "a slightly uneven W should still be found"
        assert clean["components"]["similarity"] > rough[0]["components"]["similarity"]


class TestStates:
    """
    The same W truncated at different points must report where it is in its
    life, which is the whole point of marking patterns before they complete.
    """

    def test_confirmed_once_price_closes_above_the_neckline(self):
        patterns = detect_double_patterns(w_series(tail=14), kinds=("W",))
        assert patterns[0]["state"] == "confirmed"

    def test_approaching_in_the_final_leg_near_the_neckline(self):
        patterns = detect_double_patterns(w_series(tail=9), kinds=("W",))
        assert patterns, "expected the pattern before its break"
        assert patterns[0]["state"] == "approaching"

    def test_forming_just_after_the_second_low(self):
        patterns = detect_double_patterns(w_series(tail=2), kinds=("W",))
        assert patterns, "expected the pattern while still forming"
        assert patterns[0]["state"] == "forming"


class TestDetectM:
    def test_finds_a_double_top_in_the_mirror_image(self):
        patterns = detect_double_patterns(m_series(tail=14), kinds=("M",))
        assert patterns, "expected an M"
        assert patterns[0]["kind"] == "M"

    def test_w_fixture_yields_no_m(self):
        assert detect_double_patterns(w_series(tail=14), kinds=("M",)) == []

    def test_m_fixture_yields_no_w(self):
        assert detect_double_patterns(m_series(tail=14), kinds=("W",)) == []


class TestTimeframeIndependence:
    """
    Regression guard for the bug slice 1 shipped: a fixed percentage threshold
    made levels undetectable on 1m and trivial on 1d. Thresholds are in ATR, so
    the same shape must be found whatever the magnitude of the moves.
    """

    @pytest.mark.parametrize("scale", [0.001, 1.0, 1000.0])
    def test_same_shape_detected_at_any_price_scale(self, scale):
        patterns = detect_double_patterns(w_series(tail=12, scale=scale), kinds=("W",))
        assert patterns, f"W should be found at scale {scale}"
        assert patterns[0]["state"] == "confirmed"


class TestStrictness:
    def test_stricter_settings_never_find_more(self):
        series = w_series(low2_offset=0.2, tail=12)
        strict = len(detect_double_patterns(series, strictness="strict", kinds=("W",)))
        balanced = len(detect_double_patterns(series, strictness="balanced", kinds=("W",)))
        loose = len(detect_double_patterns(series, strictness="loose", kinds=("W",)))
        assert strict <= balanced <= loose

    def test_unknown_strictness_is_rejected(self):
        with pytest.raises(ValueError):
            detect_double_patterns(w_series(tail=12), strictness="aggressive")


def combined_series(leg=20):
    """An early W that completes and breaks, then a later W still forming."""
    prices = [105.0]
    prices += ramp(prices[-1], 90, leg)
    prices += ramp(90, 100, leg)
    prices += ramp(100, 90, leg)
    prices += ramp(90, 104, leg)  # clears the neckline -> confirmed
    prices += ramp(104, 80, leg)  # drift down into the next setup
    prices += ramp(80, 92, leg)
    prices += ramp(92, 80, leg)
    prices += ramp(80, 82, leg)  # only just turning up -> forming
    return to_candles(prices)


class TestRanking:
    """
    Regression: ranking by confidence alone buried the live pattern. A long
    window holds plenty of historical double bottoms that completed cleanly and
    score in the nineties, and those would crowd out the one setup that has not
    resolved yet - which is the only one a trader can still act on.
    """

    def test_a_live_pattern_outranks_completed_ones(self):
        found = detect_double_patterns(combined_series(), max_results=None)
        states = [p["state"] for p in found]

        assert "confirmed" in states, "fixture should contain a completed pattern"
        assert found[0]["state"] != "confirmed", (
            f"a live pattern should rank first, got order {states}"
        )

    def test_results_are_capped(self):
        found = detect_double_patterns(combined_series(), max_results=2)
        assert len(found) <= 2

    def test_max_results_none_returns_everything(self):
        capped = detect_double_patterns(combined_series(), max_results=1)
        every = detect_double_patterns(combined_series(), max_results=None)
        assert len(every) >= len(capped)


class TestOverlapHandling:
    """
    Regression: dedupe originally dropped any pattern sharing a single pivot
    with one already kept. Pivots are reused constantly - one low pairs with
    many later ones - so every kept pattern silently killed a swathe of good
    ones. On 390 bars of real BTC 1h it cut roughly two dozen genuine double
    bottoms to three, including one whose two lows were four dollars apart.
    """

    def test_back_to_back_patterns_both_survive(self):
        # Two W's in sequence sharing no bars: both must be reported.
        leg = 14
        prices = [104.0]
        prices += ramp(prices[-1], 90, leg)
        prices += ramp(90, 100, leg)
        prices += ramp(100, 90, leg)
        prices += ramp(90, 103, leg)  # first W completes
        prices += ramp(103, 80, leg)
        prices += ramp(80, 92, leg)
        prices += ramp(92, 80, leg)
        prices += ramp(80, 94, leg)  # second W completes
        found = detect_double_patterns(to_candles(prices), kinds=("W",), max_results=None)

        assert len(found) >= 2, (
            f"expected both sequential patterns, got {len(found)}"
        )

    def test_a_fan_from_one_pivot_is_collapsed(self):
        # One low pairing with several nearby lows should not produce a fan of
        # near-identical patterns over the same price action.
        found = detect_double_patterns(
            w_series(tail=12), kinds=("W",), max_results=None
        )
        spans = [
            (
                min(p["index"] for p in f["points"].values()),
                max(p["index"] for p in f["points"].values()),
            )
            for f in found
        ]
        for i, a in enumerate(spans):
            for b in spans[i + 1 :]:
                overlap = min(a[1], b[1]) - max(a[0], b[0])
                shortest = min(a[1] - a[0], b[1] - b[0])
                assert overlap <= 0 or overlap / shortest <= 0.85


class TestConfidenceFloor:
    def test_nothing_survives_an_impossible_floor(self):
        series = w_series(low2_offset=0.15, tail=12)
        assert detect_double_patterns(series, min_confidence=0.0)
        assert detect_double_patterns(series, min_confidence=100.1) == []

    @pytest.mark.parametrize("floor", [0.0, 40.0, 60.0, 80.0])
    def test_everything_returned_meets_the_floor(self, floor):
        """
        The actual contract. Note that raising the floor can surface a pattern
        that a lower floor hid: filtering runs before overlap-dropping, so
        removing a winner lets the neighbour it was suppressing through. That
        is intended - the neighbour qualifies and the winner no longer does.
        """
        found = detect_double_patterns(
            combined_series(), min_confidence=floor, max_results=None
        )
        for pattern in found:
            assert pattern["confidence"] >= floor

    def test_default_floor_still_admits_a_textbook_pattern(self):
        assert detect_double_patterns(w_series(tail=12), kinds=("W",))


class TestPriceSource:
    """
    Pivots are measured on wicks by default, matching classic technical
    analysis and most published implementations. Closes remain available
    because crypto stop hunts routinely print equal wick lows that mean
    nothing.
    """

    def test_wick_source_uses_the_extremes_not_the_closes(self):
        # Wicks extend 3 below every close, so a W's shoulders should be
        # reported 3 lower than the close-based reading of the same series.
        series = w_series(tail=12, wick=3.0)
        wick = detect_double_patterns(series, kinds=("W",), source="wick")
        close = detect_double_patterns(series, kinds=("W",), source="close")

        assert wick and close, "both readings should find the pattern"
        assert wick[0]["points"]["low1"]["price"] < close[0]["points"]["low1"]["price"]

    def test_neckline_uses_the_high_for_a_w(self):
        series = w_series(tail=12, wick=3.0)
        wick = detect_double_patterns(series, kinds=("W",), source="wick")
        close = detect_double_patterns(series, kinds=("W",), source="close")
        assert wick[0]["neckline"] > close[0]["neckline"]

    def test_a_break_still_needs_a_close_beyond_the_neckline(self):
        # Wicks poke above the neckline but no candle closes above it, so the
        # pattern must not be reported as confirmed.
        leg = 20
        prices = [105.0]
        prices += ramp(prices[-1], 90, leg)
        prices += ramp(90, 100, leg)
        prices += ramp(100, 90, leg)
        prices += ramp(90, 98, leg)  # closes stay under the 100 neckline
        candles = to_candles(prices, wick=4.0)  # but wicks reach 102

        found = detect_double_patterns(candles, kinds=("W",), source="wick")
        assert found, "expected the pattern"
        assert found[0]["state"] != "confirmed", (
            "a wick through the neckline is not a break"
        )

    def test_default_source_is_wick(self):
        series = w_series(tail=12, wick=3.0)
        assert (
            detect_double_patterns(series, kinds=("W",))[0]["points"]["low1"]["price"]
            == detect_double_patterns(series, kinds=("W",), source="wick")[0]["points"][
                "low1"
            ]["price"]
        )

    def test_unknown_source_is_rejected(self):
        with pytest.raises(ValueError):
            detect_double_patterns(w_series(tail=12), source="body")


class TestRangeBoundPatterns:
    """
    Small W's inside a range are real setups that scalpers trade, so the
    detector must not require a preceding trend. Thresholds are in ATR, which
    is what lets a shallow pattern in a quiet range still qualify.
    """

    def test_a_small_w_inside_a_range_is_found(self):
        leg = 12
        prices = [100.0]
        # Sideways chop between roughly 99 and 101, no trend either side.
        for _ in range(3):
            prices += ramp(prices[-1], 101, leg)
            prices += ramp(101, 99, leg)
        # A modest W within that same range.
        prices += ramp(prices[-1], 99.0, leg)
        prices += ramp(99.0, 100.6, leg)
        prices += ramp(100.6, 99.05, leg)
        prices += ramp(99.05, 100.8, leg)
        candles = to_candles(prices)

        found = detect_double_patterns(candles, strictness="loose", kinds=("W",))
        assert found, "a range-bound W should still be detected"


class TestDegenerateInput:
    @pytest.mark.parametrize(
        "candles",
        [[], to_candles([100.0] * 5), to_candles([100.0] * 200)],
    )
    def test_empty_flat_and_short_windows_return_nothing(self, candles):
        assert detect_double_patterns(candles) == []
