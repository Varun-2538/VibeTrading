"""
Single-candle shapes. Pure functions over one closed bar.

A shape is a statement about one candle's geometry, so it is settled the
moment the candle closes and cannot repaint - unlike a W/M pattern, which is
judged against later price. That is why sequence rules default to no
persistence wait.
"""
from typing import Any, Dict, Sequence

import numpy as np

# Shapes the rule vocabulary knows. Adding one is a function here and a name in
# this tuple; analysis/sequence.py dispatches on the name.
SHAPES = ("doji",)

DEFAULT_DOJI_BODY_PCT = 10.0


def is_doji(candle: Dict[str, Any], max_body_pct: float = DEFAULT_DOJI_BODY_PCT) -> bool:
    """
    Open and close within `max_body_pct` of the bar's full range.

    A bar with no range at all (open == high == low == close) is not a doji: it
    is a bar where nothing traded, and calling that indecision would fire rules
    on illiquid gaps.
    """
    high = float(candle["high"])
    low = float(candle["low"])
    rng = high - low
    if rng <= 0:
        return False
    body = abs(float(candle["close"]) - float(candle["open"]))
    return body / rng * 100.0 <= max_body_pct


def shape_mask(candles: Sequence[Dict[str, Any]], shape: str, **params: Any) -> np.ndarray:
    """Boolean mask over `candles`: True where the bar has `shape`."""
    if shape == "doji":
        max_body = float(params.get("max_body_pct", DEFAULT_DOJI_BODY_PCT))
        return np.array([is_doji(c, max_body) for c in candles], dtype=bool)
    raise ValueError(f"Unknown candle shape {shape!r}. Expected one of: {', '.join(SHAPES)}")
