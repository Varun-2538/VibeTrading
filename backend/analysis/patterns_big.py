"""
Head and shoulders, inverse head and shoulders, cup and handle.

Built on the same pivot machinery as the double bottoms in patterns.py and
emitting the same dict - kind, state, confidence, components, points,
neckline, target - so the pattern rules, the scene, the guard and the chart
overlay need to learn only three new kind names.

Two honesty notes carried over from the W/M detector. Confirmation is always a
close beyond the neckline, never a wick. And these shapes are found in random
walks too; the test suite measures how often, and the risk page says so. A
detection is evidence that a shape is present, not that a move will follow.
"""
from typing import Any, Dict, List, Optional, Sequence

from analysis.patterns import (
    DEFAULT_SCALE,
    KINDS,
    MAX_PATTERNS,
    MIN_CONFIDENCE,
    PRESETS,
    SCALES,
    SOURCES,
    Strictness,
    _drop_overlaps,
    _point,
    _rank,
    _score,
    atr,
    detect_double_patterns,
    find_pivots,
    pivot_series,
)

BIG_KINDS = ("HS", "IHS", "CUP")
ALL_KINDS = KINDS + BIG_KINDS

# Which way each kind resolves, for the rule engine's direction.
PATTERN_BIAS = {"W": "bullish", "M": "bearish", "HS": "bearish", "IHS": "bullish", "CUP": "bullish"}

# The troughs either side of the head may differ by this many shoulder
# tolerances and still be read as one flat neckline.
NECK_TOL_FACTOR = 2.0
# A cup's bottom must sit inside this fraction of the span, else it is a V or
# a slope with a bounce, not a bowl.
CUP_BOTTOM_MIN, CUP_BOTTOM_MAX = 0.3, 0.7
# Over the middle 40% of the cup, closes may rise at most this fraction of the
# depth above the bottom. A parabola scores 0.16 here and a V 0.40: a bowl
# has a floor, a V has a point.
CUP_FLAT_MAX = 0.25
CUP_MIDDLE = 0.4
# A handle may retrace at most this fraction of the cup's depth.
HANDLE_MAX_RETRACE = 0.5
# And may take at most this fraction of the cup's span to form.
HANDLE_MAX_SPAN = 0.5


def _distinct(pivots: Sequence[int], prices: Sequence[float], min_gap: int, keep_max: bool) -> List[int]:
    """
    Collapse runs of pivots closer than `min_gap` bars into the most extreme
    one. find_pivots reports every bar that is the extreme of its window, so
    two adjacent bars with equal highs both qualify - and a walk over
    consecutive triples then never sees shoulder, head, shoulder side by side.
    """
    out: List[int] = []
    for i in pivots:
        if out and i - out[-1] < min_gap:
            better = prices[i] > prices[out[-1]] if keep_max else prices[i] < prices[out[-1]]
            if better:
                out[-1] = i
            continue
        out.append(i)
    return out


def _state(
    closes: Sequence[float],
    after_index: int,
    neckline: float,
    height: float,
    bullish: bool,
    turned_off: float,
    preset: Strictness,
) -> Optional[str]:
    """
    Where price is relative to the neckline, judged on closes.

    `turned_off` is the price of the last pivot the pattern completes on; the
    pattern only exists once price has moved away from it toward the neckline.
    """
    after = closes[after_index + 1 :]
    last = closes[-1]
    if bullish:
        broken = any(c > neckline for c in after)
        distance = neckline - last
        moving = bool(after) and last > turned_off
    else:
        broken = any(c < neckline for c in after)
        distance = last - neckline
        moving = bool(after) and last < turned_off
    if broken:
        return "confirmed"
    if moving and distance <= preset.near_frac * height:
        return "approaching"
    if moving:
        return "forming"
    return None


def _head_shoulders(
    candles: Sequence[Dict[str, Any]],
    inverse: bool,
    preset: Strictness,
    unit: float,
    k: int,
    source: str,
) -> List[Dict[str, Any]]:
    pivot_lows, pivot_highs = find_pivots(candles, k, source)
    lows, highs = pivot_series(candles, source)
    min_bars = k + 1
    pivot_lows = _distinct(pivot_lows, lows, min_bars, keep_max=False)
    pivot_highs = _distinct(pivot_highs, highs, min_bars, keep_max=True)
    # For a regular H&S the three peaks are pivot highs and the neckline runs
    # through the two pivot lows between them. Inverse flips both.
    peaks = pivot_lows if inverse else pivot_highs
    troughs = pivot_highs if inverse else pivot_lows
    peak_px = lows if inverse else highs
    trough_px = highs if inverse else lows
    sign = -1.0 if inverse else 1.0  # so "higher" means more extreme

    closes = [float(c["close"]) for c in candles]
    found: List[Dict[str, Any]] = []

    for i in range(len(peaks) - 2):
        s1, head, s2 = peaks[i], peaks[i + 1], peaks[i + 2]
        if head - s1 < min_bars or s2 - head < min_bars:
            continue
        if s2 - s1 > preset.max_bars:
            continue

        p1, ph, p2 = peak_px[s1], peak_px[head], peak_px[s2]
        # The head must stand clear of both shoulders.
        prominence = min(sign * (ph - p1), sign * (ph - p2))
        if prominence < preset.depth * unit:
            continue
        # Shoulders at roughly the same height.
        mismatch = abs(p2 - p1)
        if mismatch > preset.tol * unit:
            continue

        left = [t for t in troughs if s1 < t < head]
        right = [t for t in troughs if head < t < s2]
        if not left or not right:
            continue
        # The deepest trough on each side of the head.
        l1 = (max if inverse else min)(left, key=lambda t: trough_px[t])
        l2 = (max if inverse else min)(right, key=lambda t: trough_px[t])
        n1, n2 = trough_px[l1], trough_px[l2]
        # The head is a hill between the troughs, not a one-bar spike pressed
        # against one of them.
        if min(head - l1, l2 - head) < 0.2 * (l2 - l1):
            continue
        if abs(n2 - n1) > NECK_TOL_FACTOR * preset.tol * unit:
            continue
        neckline = (n1 + n2) / 2.0
        height = sign * (ph - neckline)
        if height <= 0:
            continue

        state = _state(closes, s2, neckline, height, inverse, p2, preset)
        if state is None:
            continue

        components = {
            "similarity": _score(mismatch, best=0.0, worst=preset.tol * unit),
            "depth": _score(prominence, best=preset.depth * unit * 4, worst=preset.depth * unit),
            "symmetry": _score(abs((head - s1) - (s2 - head)), best=0.0, worst=max(head - s1, s2 - head, 1)),
        }
        confidence = round(sum(components.values()) / len(components), 1)
        kind = "IHS" if inverse else "HS"
        found.append(
            {
                "kind": kind,
                "state": state,
                "confidence": confidence,
                "components": components,
                "points": {
                    "shoulder1": _point(candles, s1, p1),
                    "trough1": _point(candles, l1, n1),
                    "head": _point(candles, head, ph),
                    "trough2": _point(candles, l2, n2),
                    "shoulder2": _point(candles, s2, p2),
                },
                "neckline": neckline,
                "target": neckline + height if inverse else neckline - height,
            }
        )
    return found


def _cup_handle(
    candles: Sequence[Dict[str, Any]],
    preset: Strictness,
    unit: float,
    k: int,
    source: str,
) -> List[Dict[str, Any]]:
    pivot_lows, pivot_highs = find_pivots(candles, k, source)
    lows, highs = pivot_series(candles, source)
    min_bars = k + 1
    pivot_lows = _distinct(pivot_lows, lows, min_bars, keep_max=False)
    pivot_highs = _distinct(pivot_highs, highs, min_bars, keep_max=True)
    closes = [float(c["close"]) for c in candles]
    found: List[Dict[str, Any]] = []

    for a_pos, left in enumerate(pivot_highs):
        for right in pivot_highs[a_pos + 1 :]:
            span = right - left
            if span < 2 * min_bars:
                continue
            if span > preset.max_bars:
                break
            rim_l, rim_r = highs[left], highs[right]
            mismatch = abs(rim_r - rim_l)
            if mismatch > preset.tol * unit:
                continue

            between = [b for b in pivot_lows if left < b < right]
            if not between:
                continue
            bottom = min(between, key=lambda b: lows[b])
            rim = min(rim_l, rim_r)
            depth = rim - lows[bottom]
            if depth < preset.depth * unit:
                continue

            # A bowl, not a V: the low sits near the middle, and across the
            # middle of the cup the closes stay near the floor.
            pos = (bottom - left) / span
            if not (CUP_BOTTOM_MIN <= pos <= CUP_BOTTOM_MAX):
                continue
            margin = int(span * (1 - CUP_MIDDLE) / 2)
            mid = closes[left + margin : right - margin + 1]
            if not mid:
                continue
            if (max(mid) - lows[bottom]) / depth > CUP_FLAT_MAX:
                continue

            # The handle: a pullback after the right rim that holds well above
            # the bottom. The deepest pivot low within the allowed span.
            handle_window = [
                b for b in pivot_lows
                if right < b <= right + int(span * HANDLE_MAX_SPAN)
            ]
            if not handle_window:
                continue
            handle = min(handle_window, key=lambda b: lows[b])
            retrace = (rim_r - lows[handle]) / depth
            if retrace <= 0 or retrace > HANDLE_MAX_RETRACE:
                continue

            neckline = rim_r
            state = _state(closes, handle, neckline, depth, True, lows[handle], preset)
            if state is None:
                continue

            components = {
                "similarity": _score(mismatch, best=0.0, worst=preset.tol * unit),
                "depth": _score(depth, best=preset.depth * unit * 4, worst=preset.depth * unit),
                # A shallow handle is the textbook one.
                "symmetry": _score(retrace, best=0.1, worst=HANDLE_MAX_RETRACE),
            }
            confidence = round(sum(components.values()) / len(components), 1)
            found.append(
                {
                    "kind": "CUP",
                    "state": state,
                    "confidence": confidence,
                    "components": components,
                    "points": {
                        "left_rim": _point(candles, left, rim_l),
                        "bottom": _point(candles, bottom, lows[bottom]),
                        "right_rim": _point(candles, right, rim_r),
                        "handle": _point(candles, handle, lows[handle]),
                    },
                    "neckline": neckline,
                    "target": neckline + depth,
                }
            )
    return found


def detect_all_patterns(
    candles: Sequence[Dict[str, Any]],
    strictness: str = "balanced",
    kinds: Sequence[str] = ALL_KINDS,
    max_results: Optional[int] = MAX_PATTERNS,
    min_confidence: float = MIN_CONFIDENCE,
    source: str = "wick",
    scale: str = DEFAULT_SCALE,
) -> List[Dict[str, Any]]:
    """
    Every pattern kind - W, M, HS, IHS, CUP - in one ranked list.

    The double and big detectors each dedupe within their own kinds; merging
    here re-ranks the union by state, recency and confidence.
    """
    for kind in kinds:
        if kind not in ALL_KINDS:
            raise ValueError(f"Unknown pattern kind {kind!r}. Expected one of: {', '.join(ALL_KINDS)}")
    small = [k for k in kinds if k in KINDS]
    big = [k for k in kinds if k in BIG_KINDS]
    found: List[Dict[str, Any]] = []
    if small:
        found += detect_double_patterns(
            candles, strictness=strictness, kinds=small, max_results=None,
            min_confidence=min_confidence, source=source, scale=scale,
        )
    if big:
        found += detect_big_patterns(
            candles, strictness=strictness, kinds=big, max_results=None,
            min_confidence=min_confidence, source=source, scale=scale,
        )
    found.sort(key=_rank)
    return found if max_results is None else found[:max_results]


def detect_big_patterns(
    candles: Sequence[Dict[str, Any]],
    strictness: str = "balanced",
    kinds: Sequence[str] = BIG_KINDS,
    max_results: Optional[int] = MAX_PATTERNS,
    min_confidence: float = MIN_CONFIDENCE,
    source: str = "wick",
    scale: str = DEFAULT_SCALE,
) -> List[Dict[str, Any]]:
    """
    Head and shoulders, inverse, and cup and handle in a window, most
    actionable first - the same contract as detect_double_patterns.
    """
    if strictness not in PRESETS:
        raise ValueError(f"Unknown strictness {strictness!r}. Expected one of: {', '.join(PRESETS)}")
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r}. Expected one of: {', '.join(SOURCES)}")
    if scale not in SCALES:
        raise ValueError(f"Unknown scale {scale!r}. Expected one of: {', '.join(SCALES)}")
    for kind in kinds:
        if kind not in BIG_KINDS:
            raise ValueError(f"Unknown pattern kind {kind!r}. Expected one of: {', '.join(BIG_KINDS)}")

    preset = PRESETS[strictness]
    unit = atr(candles)
    if unit <= 0 or len(candles) < 14:
        return []

    found: List[Dict[str, Any]] = []
    for k in SCALES[scale]:
        if len(candles) < 2 * k + 1:
            continue
        if "HS" in kinds:
            found += _head_shoulders(candles, False, preset, unit, k, source)
        if "IHS" in kinds:
            found += _head_shoulders(candles, True, preset, unit, k, source)
        if "CUP" in kinds:
            found += _cup_handle(candles, preset, unit, k, source)

    found = [p for p in found if p["confidence"] >= min_confidence]
    found = _drop_overlaps(found)
    return found if max_results is None else found[:max_results]
