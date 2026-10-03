"""
Market structure: what price did at the levels, and which way the swings lean.

The words traders use for this - liquidity sweep, stop hunt, breakout,
rejection, pullback, "smart money" - are presented here as defined geometric
events over closed candles. A sweep is a wick that pierces a level and a close
back on the original side; nothing here claims to know who traded. That is the
only honest way to put these words in front of a chart.

No look-ahead. An event at bar i is judged against levels computed from the
bars before i, so an old bar is not labelled with a level that only exists
because of what came after it. The alert engine only ever judges the newest
closed bar, and the scene now follows the same discipline.

Thresholds are in ATR, as everywhere else in analysis/.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from analysis.levels import detect_levels
from analysis.patterns import atr as average_true_range
from analysis.patterns import find_pivots

EVENTS = ("breakout", "sweep", "rejection", "pullback")
SIDES = ("bullish", "bearish")

# How far a wick must poke through a level to count as a sweep.
SWEEP_PIERCE_ATR = 0.15
# How far a close must clear a level to count as a breakout.
BREAKOUT_CLEAR_ATR = 0.25
# Closes that must sit on the far side before a breakout counts as one.
BREAKOUT_PRIOR_BARS = 3
# A rejecting wick is at least this many times the body, and this many ATR.
REJECT_WICK_TO_BODY = 2.0
REJECT_WICK_ATR = 0.5
# A pullback is a retrace of this fraction of the last impulse leg.
PULLBACK_MIN, PULLBACK_MAX = 0.3, 0.7
# Pivot half-width for swing structure.
SWING_K = 4
# Two extremes within this many ATR of each other are equal, not higher/lower.
EQUAL_TOL_ATR = 0.1
# Bars before an event bar that levels are computed from.
LEVEL_LOOKBACK = 200


def _bar(c: Dict[str, Any]) -> Tuple[float, float, float, float]:
    return float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])


def _levels_before(candles: Sequence[Dict[str, Any]], i: int) -> List[float]:
    """Every level price the bars before i establish, both sides pooled."""
    start = max(0, i - LEVEL_LOOKBACK)
    if i - start < 10:
        return []
    found = detect_levels(list(candles[start:i]))
    return [float(l["price"]) for l in found["support_levels"] + found["resistance_levels"]]


# --- single-bar events against a level -------------------------------------


def sweep_at(candle: Dict[str, Any], level: float, unit: float) -> Optional[str]:
    """'bullish' if the bar swept lows under `level`, 'bearish' if highs over it."""
    o, h, l, c = _bar(candle)
    pierce = SWEEP_PIERCE_ATR * unit
    if l <= level - pierce and c > level and o > level - pierce * 0.5:
        return "bullish"
    if h >= level + pierce and c < level and o < level + pierce * 0.5:
        return "bearish"
    return None


def breakout_at(
    candles: Sequence[Dict[str, Any]], i: int, level: float, unit: float
) -> Optional[str]:
    """'bullish' if bar i closed above `level` after sitting below, 'bearish' mirrored."""
    if i < BREAKOUT_PRIOR_BARS:
        return None
    clear = BREAKOUT_CLEAR_ATR * unit
    close = float(candles[i]["close"])
    prior = [float(candles[j]["close"]) for j in range(i - BREAKOUT_PRIOR_BARS, i)]
    if close >= level + clear and all(p < level for p in prior):
        return "bullish"
    if close <= level - clear and all(p > level for p in prior):
        return "bearish"
    return None


def rejection_at(candle: Dict[str, Any], level: float, unit: float) -> Optional[str]:
    """'bullish' if a long lower wick spanned `level` and the bar closed above it."""
    o, h, l, c = _bar(candle)
    body = abs(c - o)
    lower = min(o, c) - l
    upper = h - max(o, c)
    min_wick = REJECT_WICK_ATR * unit
    if lower >= min_wick and lower >= REJECT_WICK_TO_BODY * max(body, 1e-9) and l <= level <= min(o, c) and c > level:
        return "bullish"
    if upper >= min_wick and upper >= REJECT_WICK_TO_BODY * max(body, 1e-9) and max(o, c) <= level <= h and c < level:
        return "bearish"
    return None


# --- swings and pullbacks ----------------------------------------------------


def swings(candles: Sequence[Dict[str, Any]], k: int = SWING_K) -> Dict[str, Any]:
    """
    Pivot highs and lows labelled HH/LH and HL/LL against the previous pivot
    of the same kind, plus a trend read from the last pair.

    Pivots are forced to alternate. find_pivots reports every bar that is the
    extreme of its window, so two adjacent bars with equal lows both qualify;
    left as two pivots the second reads as a "lower low" of the first and the
    trend flips. Of a run of same-kind pivots only the most extreme survives.
    """
    lows_idx, highs_idx = find_pivots(candles, k=k, source="wick")
    raw = sorted(
        [(i, "high", float(candles[i]["high"])) for i in highs_idx]
        + [(i, "low", float(candles[i]["low"])) for i in lows_idx]
    )

    alternating: List[Tuple[int, str, float]] = []
    for i, kind, price in raw:
        if alternating and alternating[-1][1] == kind:
            _, _, prev_price = alternating[-1]
            more_extreme = price > prev_price if kind == "high" else price < prev_price
            if more_extreme:
                alternating[-1] = (i, kind, price)
            continue
        alternating.append((i, kind, price))

    # Equal extremes are neither higher nor lower. A range that keeps
    # touching the same high must not read as a run of "lower highs".
    tol = EQUAL_TOL_ATR * average_true_range(candles)

    points: List[Dict[str, Any]] = []
    last_high = last_low = None
    for i, kind, price in alternating:
        if kind == "high":
            if last_high is None:
                label = "H"
            elif abs(price - last_high) <= tol:
                label = "EH"
            else:
                label = "HH" if price > last_high else "LH"
            last_high = price
        else:
            if last_low is None:
                label = "L"
            elif abs(price - last_low) <= tol:
                label = "EL"
            else:
                label = "HL" if price > last_low else "LL"
            last_low = price
        points.append({"label": label, "t": int(candles[i]["time"]), "price": price, "index": i})

    labels = [p["label"] for p in points]
    recent_h = ([x for x in labels if x in ("HH", "LH")] or [None])[-1]
    recent_l = ([x for x in labels if x in ("HL", "LL")] or [None])[-1]
    if recent_h == "HH" and recent_l == "HL":
        trend = "uptrend"
    elif recent_h == "LH" and recent_l == "LL":
        trend = "downtrend"
    else:
        trend = "range"
    return {"trend": trend, "points": points}


def pullback(candles: Sequence[Dict[str, Any]], structure: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Is the newest bar a pullback inside the prevailing trend?

    Uptrend: the impulse is the last HL to the last HH; price has given back
    30-70% of it and still closes above that HL. Downtrend is the mirror.
    """
    if not candles:
        return None
    pts = structure["points"]
    close = float(candles[-1]["close"])
    trend = structure["trend"]

    if trend == "uptrend":
        hl = next((p for p in reversed(pts) if p["label"] == "HL"), None)
        hh = next((p for p in reversed(pts) if p["label"] == "HH"), None)
        if not hl or not hh or hh["index"] <= hl["index"]:
            return None
        leg = hh["price"] - hl["price"]
        if leg <= 0:
            return None
        retrace = (hh["price"] - close) / leg
        if PULLBACK_MIN <= retrace <= PULLBACK_MAX and close > hl["price"]:
            return {"side": "bullish", "retrace": round(retrace, 2), "from": hh, "holds": hl}
    elif trend == "downtrend":
        lh = next((p for p in reversed(pts) if p["label"] == "LH"), None)
        ll = next((p for p in reversed(pts) if p["label"] == "LL"), None)
        if not lh or not ll or ll["index"] <= lh["index"]:
            return None
        leg = lh["price"] - ll["price"]
        if leg <= 0:
            return None
        retrace = (close - ll["price"]) / leg
        if PULLBACK_MIN <= retrace <= PULLBACK_MAX and close < lh["price"]:
            return {"side": "bearish", "retrace": round(retrace, 2), "from": ll, "holds": lh}
    return None


# --- events over a window ----------------------------------------------------


def events_at(candles: Sequence[Dict[str, Any]], i: int, unit: float) -> List[Dict[str, Any]]:
    """Every level event on bar i, judged against levels from the bars before it."""
    out: List[Dict[str, Any]] = []
    levels = _levels_before(candles, i)
    if not levels or unit <= 0:
        return out
    t = int(candles[i]["time"])
    for level in levels:
        side = sweep_at(candles[i], level, unit)
        if side:
            out.append({"event": "sweep", "side": side, "level": level, "t": t})
            continue  # a sweep is the more specific reading of the same wick
        side = breakout_at(candles, i, level, unit)
        if side:
            out.append({"event": "breakout", "side": side, "level": level, "t": t})
        side = rejection_at(candles[i], level, unit)
        if side:
            out.append({"event": "rejection", "side": side, "level": level, "t": t})
    return out


def recent_events(candles: Sequence[Dict[str, Any]], bars: int) -> List[Dict[str, Any]]:
    """Level events on the last `bars` bars, newest first."""
    unit = average_true_range(candles)
    out: List[Dict[str, Any]] = []
    for i in range(max(0, len(candles) - bars), len(candles)):
        out.extend(events_at(candles, i, unit))
    out.sort(key=lambda e: e["t"], reverse=True)
    return out


def event_masks(
    candles: Sequence[Dict[str, Any]], tail: int
) -> Dict[Tuple[str, str], np.ndarray]:
    """
    Boolean masks keyed by (event, side) over `candles`, computed for the last
    `tail` bars only. Level detection per bar is the cost, and a sequence rule
    never needs an event further back than its window.
    """
    n = len(candles)
    masks = {(e, s): np.zeros(n, dtype=bool) for e in EVENTS for s in SIDES}
    if n == 0:
        return masks
    unit = average_true_range(candles)
    for i in range(max(0, n - tail), n):
        for ev in events_at(candles, i, unit):
            masks[(ev["event"], ev["side"])][i] = True
    # Pullback is a state of the newest bar, not a level event.
    pb = pullback(candles, swings(candles))
    if pb:
        masks[("pullback", pb["side"])][n - 1] = True
    return masks
