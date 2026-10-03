"""
Candlestick shapes. Pure functions over one closed bar and, for the two-bar
shapes, the bar before it.

A shape is a statement about a candle's geometry, so it is settled the moment
the candle closes and cannot repaint - unlike a W/M pattern, which is judged
against later price. That is why sequence rules default to no persistence
wait.

Size thresholds are in ATR, not percent, for the reason patterns.py gives:
a percentage calibrated for a daily chart is meaningless on a 1-minute one.
A "hammer" whose whole range is a fraction of an average bar is noise, and
the ATR floor is what keeps it out.
"""
from typing import Any, Dict, Sequence

import numpy as np

from analysis.patterns import atr as average_true_range

# Shapes the rule vocabulary knows. Adding one is a function here, an entry in
# this tuple, and a bias below; the rule schema, the scene and the parser read
# from these.
SHAPES = (
    "doji",
    "hammer",
    "shooting_star",
    "bullish_engulfing",
    "bearish_engulfing",
    "inside_bar",
)

# What a shape leans toward on its own, for a sequence rule that ends on one.
SHAPE_BIAS = {
    "doji": "neutral",
    "hammer": "bullish",
    "shooting_star": "bearish",
    "bullish_engulfing": "bullish",
    "bearish_engulfing": "bearish",
    "inside_bar": "neutral",
}

DEFAULT_DOJI_BODY_PCT = 10.0

# A bar must span at least this many ATR to carry a single-bar shape. Below
# it the geometry is real but the bar is too small to mean anything.
MIN_RANGE_ATR = 0.5
# A body this small (in ATR) does not count as a "real" body for engulfing.
MIN_BODY_ATR = 0.1
# The rejecting wick of a hammer or shooting star must be at least this many
# times the body, and the other wick at most this fraction of the range.
WICK_TO_BODY = 2.0
OTHER_WICK_MAX = 0.25


def _parts(candle: Dict[str, Any]):
    o, h, l, c = (float(candle[k]) for k in ("open", "high", "low", "close"))
    body = abs(c - o)
    rng = h - l
    upper = h - max(o, c)
    lower = min(o, c) - l
    return o, h, l, c, body, rng, upper, lower


def is_doji(candle: Dict[str, Any], max_body_pct: float = DEFAULT_DOJI_BODY_PCT) -> bool:
    """
    Open and close within `max_body_pct` of the bar's full range.

    A bar with no range at all (open == high == low == close) is not a doji: it
    is a bar where nothing traded, and calling that indecision would fire rules
    on illiquid gaps.
    """
    _, _, _, _, body, rng, _, _ = _parts(candle)
    if rng <= 0:
        return False
    return body / rng * 100.0 <= max_body_pct


def is_hammer(candle: Dict[str, Any], unit: float) -> bool:
    """
    Long lower wick, small body near the top, little or no upper wick: price
    was pushed down and rejected. Body colour does not matter.
    """
    _, _, _, _, body, rng, upper, lower = _parts(candle)
    if rng <= 0 or rng < MIN_RANGE_ATR * unit:
        return False
    if body == 0:
        # A doji with a long lower wick is a dragonfly; count it, since the
        # rejection is the point and the body is as small as it gets.
        return lower >= rng * 0.6 and upper <= rng * OTHER_WICK_MAX
    return lower >= WICK_TO_BODY * body and upper <= rng * OTHER_WICK_MAX


def is_shooting_star(candle: Dict[str, Any], unit: float) -> bool:
    """The mirror of a hammer: long upper wick, body near the bottom."""
    _, _, _, _, body, rng, upper, lower = _parts(candle)
    if rng <= 0 or rng < MIN_RANGE_ATR * unit:
        return False
    if body == 0:
        return upper >= rng * 0.6 and lower <= rng * OTHER_WICK_MAX
    return upper >= WICK_TO_BODY * body and lower <= rng * OTHER_WICK_MAX


def is_bullish_engulfing(prev: Dict[str, Any], candle: Dict[str, Any], unit: float) -> bool:
    """
    A down bar followed by an up bar whose body covers the previous body.

    Both bodies must be real: engulfing a one-tick body is not a reversal, and
    an engulfing bar that is itself a sliver is not either.
    """
    po, _, _, pc, pbody, _, _, _ = _parts(prev)
    o, _, _, c, body, _, _, _ = _parts(candle)
    if pc >= po or c <= o:
        return False
    if pbody < MIN_BODY_ATR * unit or body < MIN_BODY_ATR * unit:
        return False
    return o <= pc and c >= po


def is_bearish_engulfing(prev: Dict[str, Any], candle: Dict[str, Any], unit: float) -> bool:
    """An up bar followed by a down bar whose body covers the previous body."""
    po, _, _, pc, pbody, _, _, _ = _parts(prev)
    o, _, _, c, body, _, _, _ = _parts(candle)
    if pc <= po or c >= o:
        return False
    if pbody < MIN_BODY_ATR * unit or body < MIN_BODY_ATR * unit:
        return False
    return o >= pc and c <= po


def is_inside_bar(prev: Dict[str, Any], candle: Dict[str, Any], unit: float) -> bool:
    """
    The whole bar sits inside the previous bar's range: consolidation after
    a move. The mother bar must be a real bar, or every quiet stretch is a
    run of inside bars.
    """
    _, ph, pl, _, _, prng, _, _ = _parts(prev)
    _, h, l, _, _, _, _, _ = _parts(candle)
    if prng < MIN_RANGE_ATR * unit:
        return False
    return h <= ph and l >= pl


def shape_masks(candles: Sequence[Dict[str, Any]], **params: Any) -> Dict[str, np.ndarray]:
    """Every shape's mask over `candles`, with the ATR computed once."""
    n = len(candles)
    unit = average_true_range(candles) if n >= 2 else 0.0
    max_body = float(params.get("max_body_pct", DEFAULT_DOJI_BODY_PCT))

    out = {shape: np.zeros(n, dtype=bool) for shape in SHAPES}
    for i, c in enumerate(candles):
        out["doji"][i] = is_doji(c, max_body)
        if unit > 0:
            out["hammer"][i] = is_hammer(c, unit)
            out["shooting_star"][i] = is_shooting_star(c, unit)
            if i > 0:
                p = candles[i - 1]
                out["bullish_engulfing"][i] = is_bullish_engulfing(p, c, unit)
                out["bearish_engulfing"][i] = is_bearish_engulfing(p, c, unit)
                out["inside_bar"][i] = is_inside_bar(p, c, unit)
    return out


def shape_mask(candles: Sequence[Dict[str, Any]], shape: str, **params: Any) -> np.ndarray:
    """Boolean mask over `candles`: True where the bar has `shape`."""
    if shape not in SHAPES:
        raise ValueError(f"Unknown candle shape {shape!r}. Expected one of: {', '.join(SHAPES)}")
    return shape_masks(candles, **params)[shape]
