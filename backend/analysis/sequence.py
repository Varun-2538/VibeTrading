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

# Bars a step may lag its predecessor by, if the rule does not say.
DEFAULT_WITHIN_BARS = 3


def step_mask(candles: Sequence[Dict[str, Any]], step: Dict[str, Any]) -> np.ndarray:
    """Boolean mask over `candles` for one step."""
    kind = step.get("type")

    if kind == "candle":
        return candle_shapes.shape_mask(
            candles,
            step["shape"],
            max_body_pct=step.get("max_body_pct", candle_shapes.DEFAULT_DOJI_BODY_PCT),
        )

    if kind == "indicator":
        name = step.get("indicator")
        closes = np.array([float(c["close"]) for c in candles], dtype=float)
        if name == "rsi":
            series = indicators.rsi(closes, int(step.get("period", 14)))
            return indicators.crosses(series, float(step["level"]), step["cross"])
        raise ValueError(
            f"Unknown indicator {name!r}. Expected one of: {', '.join(indicators.INDICATORS)}"
        )

    raise ValueError(f"Unknown step type {kind!r}. Expected 'candle' or 'indicator'.")


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
    return ", then ".join(parts)
