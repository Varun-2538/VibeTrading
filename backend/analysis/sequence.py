"""
Ordered event sequences over closed candles.

A sequence rule is "A, then B, within N bars" - for example a doji followed by
RSI crossing above 30. Each step is turned into a boolean mask over the bars,
and the matcher walks the masks in order. The final step is required to land on
the newest closed bar: that is what makes a match mean "this just completed"
rather than "this happened somewhere in the lookback", and it gives the match a
stable identity for dedup.
"""
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from analysis import candles as candle_shapes
from analysis import indicators
from analysis.indicators import (
    atr_series,
    bollinger,
    crosses,
    crosses_series,
    ema,
    macd,
    rsi,
    stochastic,
    true_range,
    volume_ratio,
    vwap,
)
from analysis import structure

MASK_STEPS = (
    "candle", "indicator", "structure", "ema_cross", "macd_cross", "stoch_cross",
    "bollinger", "bollinger_squeeze", "vwap_cross", "volume_spike", "atr_expansion",
)

# Bars a step may lag its predecessor by, if the rule does not say.
DEFAULT_WITHIN_BARS = 3

# How far back structure events are computed for a sequence step.
STRUCTURE_TAIL_BARS = 60


def step_mask(candles: Sequence[Dict[str, Any]], step: Dict[str, Any]) -> np.ndarray:
    """Boolean mask over `candles` for one step."""
    kind = step.get("type")

    if kind == "candle":
        return candle_shapes.shape_mask(
            candles,
            step["shape"],
            max_body_pct=step.get("max_body_pct", candle_shapes.DEFAULT_DOJI_BODY_PCT),
        )

    if kind == "structure":
        # Level events are computed for the tail of the window only; a
        # sequence never needs one further back than its steps can reach.
        masks = structure.event_masks(candles, tail=STRUCTURE_TAIL_BARS)
        key = (step.get("event"), step.get("side"))
        if key not in masks:
            raise ValueError(
                f"Unknown structure step {key!r}. Expected event in "
                f"{', '.join(structure.EVENTS)} and side in {', '.join(structure.SIDES)}."
            )
        return masks[key]

    closes = np.array([float(c["close"]) for c in candles], dtype=float)
    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)
    volumes = np.array([float(c["volume"]) for c in candles], dtype=float)
    times = np.array([int(c["time"]) for c in candles], dtype=np.int64)

    if kind == "indicator":
        name = step.get("indicator")
        if name == "rsi":
            series = indicators.rsi(closes, int(step.get("period", 14)))
            return indicators.crosses(series, float(step["level"]), step["cross"])
        raise ValueError(
            f"Unknown indicator {name!r}. Expected one of: {', '.join(indicators.INDICATORS)}"
        )

    if kind == "ema_cross":
        fast = closes if int(step.get("fast", 20)) == 1 else ema(closes, int(step.get("fast", 20)))
        slow = ema(closes, int(step.get("slow", 50)))
        return crosses_series(fast, slow, step.get("cross", "above"))

    if kind == "macd_cross":
        line, signal_line, _ = macd(
            closes,
            fast_period=int(step.get("fast", 12)),
            slow_period=int(step.get("slow", 26)),
            signal_period=int(step.get("signal", 9)),
        )
        other = np.zeros(line.shape) if step.get("against") == "zero" else signal_line
        return crosses_series(line, other, step.get("cross", "above"))

    if kind == "stoch_cross":
        k, d = stochastic(
            highs, lows, closes,
            k_period=int(step.get("k", 14)),
            k_smooth=int(step.get("k_smooth", 3)),
            d_period=int(step.get("d", 3)),
        )
        if step.get("against") == "level":
            return crosses(k, float(step.get("level", 20.0)), step.get("cross", "above"))
        return crosses_series(k, d, step.get("cross", "above"))

    if kind == "bollinger":
        middle, upper, lower, _ = bollinger(
            closes, period=int(step.get("period", 20)), std=float(step.get("std", 2.0))
        )
        band = {"upper": upper, "middle": middle, "lower": lower}[step.get("band", "upper")]
        return crosses_series(closes, band, step.get("cross", "above"))

    if kind == "bollinger_squeeze":
        _, _, _, width = bollinger(
            closes, period=int(step.get("period", 20)), std=float(step.get("std", 2.0))
        )
        lookback = int(step.get("lookback", 120))
        out = np.zeros(closes.shape, dtype=bool)
        for i in range(closes.size):
            window = width[max(0, i + 1 - lookback): i + 1]
            if np.isnan(width[i]) or np.isnan(window).all():
                continue
            # The tightest bandwidth of the window, this bar included.
            out[i] = width[i] <= np.nanmin(window)
        return out

    if kind == "vwap_cross":
        line = vwap(highs, lows, closes, volumes, times, anchor=step.get("anchor", "day"))
        return crosses_series(closes, line, step.get("cross", "above"))

    if kind == "volume_spike":
        ratio = volume_ratio(volumes, period=int(step.get("period", 20)))
        with np.errstate(invalid="ignore"):
            return np.nan_to_num(ratio, nan=0.0) >= float(step.get("multiple", 2.0))

    if kind == "atr_expansion":
        ranges = true_range(highs, lows, closes)
        unit = atr_series(highs, lows, closes, period=int(step.get("period", 14)))
        with np.errstate(invalid="ignore"):
            wide = np.nan_to_num(ranges, nan=0.0) >= float(step.get("multiple", 2.0)) * np.nan_to_num(unit, nan=np.inf)
        return wide

    raise ValueError(
        f"Unknown step type {kind!r}. Expected one of: " + ", ".join(MASK_STEPS)
    )


def match_sequence(
    candles: Sequence[Dict[str, Any]],
    steps: Sequence[Dict[str, Any]],
    within_bars: int = DEFAULT_WITHIN_BARS,
) -> Optional[List[int]]:
    """
    Indices of the bars that satisfy `steps` in order, or None.

    The last step must be true on the last bar. Earlier steps are searched
    backwards from there, each required to sit strictly before its successor
    and no more than `within_bars` before it. When several bars could serve a
    step, the nearest one wins - the most recent doji before the cross is the
    one a trader would point at.
    """
    if not steps or len(candles) < len(steps):
        return None

    masks = [step_mask(candles, step) for step in steps]
    last = len(candles) - 1
    if not masks[-1][last]:
        return None

    picked = [last]
    for mask in reversed(masks[:-1]):
        successor = picked[-1]
        earliest = max(0, successor - within_bars)
        found = None
        for i in range(successor - 1, earliest - 1, -1):
            if mask[i]:
                found = i
                break
        if found is None:
            return None
        picked.append(found)

    picked.reverse()
    return picked


def describe_steps(steps: Sequence[Dict[str, Any]]) -> str:
    """One line a human can read back: 'doji, then RSI(14) crosses above 30'."""
    parts = []
    for step in steps:
        if step.get("type") == "candle":
            parts.append(step["shape"])
        elif step.get("type") == "indicator":
            parts.append(
                f"{step['indicator'].upper()}({step.get('period', 14)}) "
                f"crosses {step['cross']} {step['level']:g}"
            )
        elif step.get("type") == "structure":
            parts.append(f"{step['side']} {step['event']}")
        elif step.get("type") == "ema_cross":
            fast = int(step.get("fast", 20))
            left = "close" if fast == 1 else f"EMA({fast})"
            parts.append(f"{left} crosses {step.get('cross', 'above')} EMA({step.get('slow', 50)})")
        elif step.get("type") == "macd_cross":
            against = "zero" if step.get("against") == "zero" else "its signal line"
            parts.append(f"MACD crosses {step.get('cross', 'above')} {against}")
        elif step.get("type") == "stoch_cross":
            if step.get("against") == "level":
                target = f"{float(step.get('level', 20)):g}"
            else:
                target = "%D"
            parts.append(f"stochastic %K crosses {step.get('cross', 'above')} {target}")
        elif step.get("type") == "bollinger":
            parts.append(
                f"close crosses {step.get('cross', 'above')} the {step.get('band', 'upper')} Bollinger band"
            )
        elif step.get("type") == "bollinger_squeeze":
            parts.append(f"Bollinger squeeze (tightest in {int(step.get('lookback', 120))} bars)")
        elif step.get("type") == "vwap_cross":
            anchor = "weekly" if step.get("anchor") == "week" else "daily"
            parts.append(f"close crosses {step.get('cross', 'above')} the {anchor} VWAP")
        elif step.get("type") == "volume_spike":
            parts.append(f"volume {float(step.get('multiple', 2.0)):g}x its average")
        elif step.get("type") == "atr_expansion":
            parts.append(f"range {float(step.get('multiple', 2.0)):g}x ATR")
    return ", then ".join(parts)
