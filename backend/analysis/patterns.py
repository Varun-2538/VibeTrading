"""
Double bottom (W) and double top (M) detection.

A double bottom is two lows at roughly the same price with a peak between them.
The peak is the neckline: price breaking above it is what confirms the pattern,
and the distance from the lows up to it projects the measured move.

Patterns are reported while they are still developing, not only once they
complete, because a confirmed break has already given up most of the move. A
pattern is `forming` once the second low is in and price has turned up,
`approaching` once price is in its final leg close to the neckline, and
`confirmed` once a close clears it.

Every threshold is expressed in ATR rather than as a percentage of price. A
fixed percentage cannot work across timeframes - a thousand 1m candles span a
fraction of a percent, so a 2% rule finds nothing there and everything on a
daily chart. That mistake shipped once already in this codebase, in the level
clustering, and is deliberately designed out here.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple


ATR_PERIOD = 14

# Reported patterns per window. A noisy chart should not bury the price action.
MAX_PATTERNS = 8

# Patterns scoring below this are dropped. Passing every threshold is a low bar
# - a shape can clear all three and still be a poor example of one - and since
# ranking puts live patterns first, without a floor a barely-qualifying forming
# pattern outranks every good confirmed one and gets drawn most prominently.
MIN_CONFIDENCE = 40.0


class Strictness:
    """
    How willing the detector is to call something a double bottom.

    tol        how closely the two shoulders must match, in ATR
    depth      how far the neckline must sit from them, in ATR
    near_frac  how close to the neckline counts as the final approach, as a
               fraction of the pattern's own height
    k          half-width of the swing-pivot window

    tol and depth are in ATR because both ask whether a move is meaningful
    against the prevailing noise. Proximity to the neckline is not that kind of
    question - it asks how far through its final leg price has travelled - so
    it is a fraction of the pattern height. Measuring it in ATR as well would
    make the approach band depend on how jumpy the candles happen to be, and on
    a quiet chart price would jump from forming straight to confirmed without
    ever being seen to approach.
    """

    def __init__(self, tol, depth, near_frac, min_bars, max_bars, k):
        self.tol = tol
        self.depth = depth
        self.near_frac = near_frac
        self.min_bars = min_bars
        self.max_bars = max_bars
        self.k = k


PRESETS: Dict[str, Strictness] = {
    "strict": Strictness(tol=0.25, depth=2.5, near_frac=0.15, min_bars=12, max_bars=120, k=5),
    "balanced": Strictness(tol=0.5, depth=1.5, near_frac=0.25, min_bars=8, max_bars=120, k=4),
    "loose": Strictness(tol=1.0, depth=1.0, near_frac=0.40, min_bars=5, max_bars=150, k=3),
}

KINDS = ("W", "M")

# Which prices the shape is measured on. Wicks are the classic definition and
# the default; closes ignore spikes. Note that neither changes how a break is
# judged - that is always a close beyond the neckline.
SOURCES = ("wick", "close")


def atr(candles: Sequence[Dict[str, Any]], period: int = ATR_PERIOD) -> float:
    """
    Average true range - the unit every threshold here is measured in.

    True range accounts for gaps by including the previous close, so a candle
    that opens away from the last one is not counted as a small move.
    """
    if len(candles) < 2:
        return 0.0

    ranges = []
    for i in range(1, len(candles)):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        prev_close = float(candles[i - 1]["close"])
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    window = ranges[-period:] if len(ranges) > period else ranges
    return sum(window) / len(window) if window else 0.0


def pivot_series(
    candles: Sequence[Dict[str, Any]], source: str = "wick"
) -> Tuple[List[float], List[float]]:
    """
    The two price series pivots are measured against: (lows, highs).

    With "wick" the extremes are used, which is how classic technical analysis
    defines a double bottom and what most published implementations do. With
    "close" both series are the closes, so a single spike cannot define a
    pattern the body of the price action does not support - steadier in crypto,
    where stop hunts routinely print equal wick lows that mean nothing.
    """
    if source == "wick":
        return (
            [float(c["low"]) for c in candles],
            [float(c["high"]) for c in candles],
        )
    if source == "close":
        closes = [float(c["close"]) for c in candles]
        return closes, list(closes)
    raise ValueError(f"Unknown source '{source}'. Expected one of: wick, close")


def find_pivots(
    candles: Sequence[Dict[str, Any]], k: int = 4, source: str = "wick"
) -> Tuple[List[int], List[int]]:
    """
    Indices of swing lows and swing highs.

    A swing low is the lowest price within k bars either side; a swing high
    mirrors it. See pivot_series for what "price" means here.

    The first and last k bars cannot be pivots - there is not enough either
    side to know - which is why a pattern only appears once price has moved on
    from its second low.
    """
    pivot_lows: List[int] = []
    pivot_highs: List[int] = []
    if len(candles) < 2 * k + 1:
        return pivot_lows, pivot_highs

    lows, highs = pivot_series(candles, source)

    for i in range(k, len(candles) - k):
        low_window = lows[i - k : i + k + 1]
        high_window = highs[i - k : i + k + 1]
        # Strict inequality on one side keeps a flat run from reporting every
        # bar in it as a pivot.
        if lows[i] == min(low_window) and lows[i] < lows[i - k]:
            pivot_lows.append(i)
        if highs[i] == max(high_window) and highs[i] > highs[i - k]:
            pivot_highs.append(i)

    return pivot_lows, pivot_highs


def _score(value: float, best: float, worst: float) -> float:
    """Map a measurement onto 0-100, where `best` scores 100."""
    if best == worst:
        return 100.0
    ratio = (value - worst) / (best - worst)
    return round(max(0.0, min(1.0, ratio)) * 100, 1)


def _point(candles, index, price) -> Dict[str, Any]:
    return {
        "time": int(candles[index]["time"]),
        "price": float(price),
        "index": index,
    }


def _detect_one_kind(
    candles: Sequence[Dict[str, Any]],
    kind: str,
    preset: Strictness,
    unit: float,
    source: str = "wick",
) -> List[Dict[str, Any]]:
    """
    Find every W (or M) in the window.

    M is the same geometry upside down, so the comparisons are written once and
    the sign flips: for an M the "lows" are pivot highs, the neckline sits below
    them, and a break is a close underneath it.

    Geometry comes from the pivot series, but the break and the current state
    are always judged on closes. A wick poking through the neckline is not a
    break - the candle has to close beyond it - which is the standard reading
    and stops a single stop-hunt spike from confirming a pattern.
    """
    is_w = kind == "W"
    pivot_lows, pivot_highs = find_pivots(candles, preset.k, source)

    # For a W the shoulders are lows and the neckline is the high between them.
    shoulders = pivot_lows if is_w else pivot_highs
    necks = pivot_highs if is_w else pivot_lows
    if len(shoulders) < 2 or not necks:
        return []

    lows, highs = pivot_series(candles, source)
    shoulder_prices = lows if is_w else highs
    neck_prices = highs if is_w else lows

    closes = [float(c["close"]) for c in candles]
    last_close = closes[-1]
    found: List[Dict[str, Any]] = []

    for a_pos, first in enumerate(shoulders):
        for second in shoulders[a_pos + 1 :]:
            separation = second - first
            if separation < preset.min_bars:
                continue
            if separation > preset.max_bars:
                break  # shoulders are ordered, so everything later is further

            between = [n for n in necks if first < n < second]
            if not between:
                continue
            # The most pronounced turn between the shoulders is the neckline.
            neck = (max if is_w else min)(between, key=lambda i: neck_prices[i])

            p_first = shoulder_prices[first]
            p_second = shoulder_prices[second]
            p_neck = neck_prices[neck]

            # The two shoulders must sit at roughly the same price.
            mismatch = abs(p_second - p_first)
            if mismatch > preset.tol * unit:
                continue

            # The neckline must be a real move away from them, not a ripple.
            height = (p_neck - max(p_first, p_second)) if is_w else (min(p_first, p_second) - p_neck)
            if height < preset.depth * unit:
                continue

            # Where is price now, relative to the neckline?
            after = closes[second + 1 :]
            broken = any(c > p_neck for c in after) if is_w else any(c < p_neck for c in after)
            distance = (p_neck - last_close) if is_w else (last_close - p_neck)
            moving_up = bool(after) and (
                last_close > p_second if is_w else last_close < p_second
            )

            if broken:
                state = "confirmed"
            elif moving_up and distance <= preset.near_frac * height:
                state = "approaching"
            elif moving_up:
                state = "forming"
            else:
                # Price has not turned off the second shoulder yet; there is no
                # pattern to speak of, only two lows.
                continue

            leg_one = neck - first
            leg_two = second - neck
            components = {
                "similarity": _score(mismatch, best=0.0, worst=preset.tol * unit),
                # Scored out to four times the minimum: at twice it saturated
                # at 100 for almost every real pattern, so the term carried no
                # information.
                "depth": _score(height, best=preset.depth * unit * 4, worst=preset.depth * unit),
                "symmetry": _score(
                    abs(leg_one - leg_two), best=0.0, worst=max(leg_one, leg_two, 1)
                ),
            }
            confidence = round(sum(components.values()) / len(components), 1)

            found.append(
                {
                    "kind": kind,
                    "state": state,
                    "confidence": confidence,
                    "components": components,
                    "points": {
                        "low1" if is_w else "high1": _point(candles, first, p_first),
                        "peak" if is_w else "trough": _point(candles, neck, p_neck),
                        "low2" if is_w else "high2": _point(candles, second, p_second),
                    },
                    "neckline": p_neck,
                    "target": p_neck + height if is_w else p_neck - height,
                }
            )

    return found


# Ranking order for the states. Only a pattern at the right-hand edge of the
# window can be forming or approaching, because both are judged against the
# latest close - so those are always the ones worth showing. Ranking by
# confidence alone buried them: a long window holds plenty of historical
# double bottoms that completed cleanly and score in the nineties, and eight
# of those would crowd out the one setup that has not resolved yet.
STATE_RANK = {"approaching": 0, "forming": 1, "confirmed": 2}


def _last_index(pattern: Dict[str, Any]) -> int:
    return max(p["index"] for p in pattern["points"].values())


def _rank(pattern: Dict[str, Any]) -> Tuple[int, int, float]:
    """Actionable first, then most recent, then most convincing."""
    return (
        STATE_RANK[pattern["state"]],
        -_last_index(pattern),
        -pattern["confidence"],
    )


def _drop_overlaps(patterns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Collapse detections that share a pivot, keeping the best ranked.

    Without this a single low pairs with several later ones and the chart shows
    a fan of near-identical patterns over the same price action.
    """
    kept: List[Dict[str, Any]] = []
    for pattern in sorted(patterns, key=_rank):
        indices = {p["index"] for p in pattern["points"].values()}
        if any(indices & {p["index"] for p in k["points"].values()} for k in kept):
            continue
        kept.append(pattern)
    return kept


def detect_double_patterns(
    candles: Sequence[Dict[str, Any]],
    strictness: str = "balanced",
    kinds: Sequence[str] = KINDS,
    max_results: Optional[int] = MAX_PATTERNS,
    min_confidence: float = MIN_CONFIDENCE,
    source: str = "wick",
) -> List[Dict[str, Any]]:
    """
    Double bottoms and double tops in a window, most actionable first.

    Ordering is by state, then recency, then confidence - see STATE_RANK.
    Pass max_results=None for everything found, which is how the API reports
    how many a given strictness actually matched rather than how many fit on
    the chart.

    Returns an empty list rather than raising for windows too short, too flat,
    or simply without patterns - the caller clears its overlay.
    """
    if strictness not in PRESETS:
        raise ValueError(
            f"Unknown strictness '{strictness}'. Expected one of: {', '.join(PRESETS)}"
        )
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError(f"Unknown pattern kind '{kind}'. Expected one of: W, M")
    if source not in SOURCES:
        raise ValueError(
            f"Unknown source '{source}'. Expected one of: {', '.join(SOURCES)}"
        )

    preset = PRESETS[strictness]
    if len(candles) < max(2 * preset.k + 1, ATR_PERIOD):
        return []

    unit = atr(candles)
    if unit <= 0:
        # A flat window: every ATR-scaled threshold would collapse to zero and
        # match indiscriminately.
        return []

    found: List[Dict[str, Any]] = []
    for kind in kinds:
        found += _detect_one_kind(candles, kind, preset, unit, source)

    found = [p for p in found if p["confidence"] >= min_confidence]
    ranked = _drop_overlaps(found)
    return ranked if max_results is None else ranked[:max_results]
