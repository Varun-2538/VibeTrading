"""
Does the signal predict anything?

For each signal: the return over the next 1, 5, 10 and 20 bars in the
signal's direction, and how far price went for and against it. Compared with
the same measurement over every bar in the period, taken in the same mix of
longs and shorts - a bullish signal in a bull market has to beat the bull
market, not zero. The edge carries a bootstrap confidence interval, so "no edge"
is an answer the report can give plainly.

Seen and unseen are studied separately, and no seen measurement reads a price
from the unseen slice.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from analysis.patterns import atr
from backtest.signals import TapeSignal

HORIZONS = (1, 5, 10, 20)
HEADLINE_HORIZON = 10
EXCURSION_BARS = 20
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 7
MIN_SIGNALS = 30
ATR_BARS = 15  # ATR(14) needs 15 bars


def _r(value: Optional[float], places: int = 4) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return round(value, places) if math.isfinite(value) else None


def signed(direction: str, neutral: str) -> Optional[int]:
    if direction == "bullish":
        return 1
    if direction == "bearish":
        return -1
    return {"long": 1, "short": -1}.get(neutral)


def bootstrap_ci(values: np.ndarray, baseline: float) -> Tuple[float, float]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    picks = rng.integers(0, values.size, size=(BOOTSTRAP_SAMPLES, values.size))
    edges = values[picks].mean(axis=1) - baseline
    return float(np.percentile(edges, 2.5)), float(np.percentile(edges, 97.5))


def period_study(
    candles: Sequence[Dict[str, Any]],
    signals: Sequence[TapeSignal],
    lo: int,
    hi: int,
    neutral: str,
) -> Dict[str, Any]:
    closes = np.array([float(c["close"]) for c in candles], dtype=float)
    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)

    in_period = [s for s in signals if lo <= s.index < hi]
    directed = [(s.index, signed(s.direction, neutral)) for s in in_period]
    usable = [(i, d) for i, d in directed if d is not None]
    skipped = len(directed) - len(usable)
    long_share = float(np.mean([d == 1 for _, d in usable])) if usable else 0.5

    horizons: List[Dict[str, Any]] = []
    for h in HORIZONS:
        values = np.array([d * (closes[i + h] / closes[i] - 1) for i, d in usable if i + h < hi], dtype=float)
        idx = np.arange(lo, max(lo, hi - h))
        market = closes[idx + h] / closes[idx] - 1 if idx.size else np.array([], dtype=float)

        baseline = (2 * long_share - 1) * float(market.mean()) if market.size else None
        base_hit = (
            long_share * float((market > 0).mean()) + (1 - long_share) * float((market < 0).mean())
            if market.size else None
        )
        mean = float(values.mean()) if values.size else None
        edge = mean - baseline if mean is not None and baseline is not None else None
        ci = bootstrap_ci(values, baseline) if values.size >= 2 and baseline is not None else None

        horizons.append({
            "h": h,
            "signals": int(values.size),
            "mean_pct": _r(mean * 100) if mean is not None else None,
            "baseline_pct": _r(baseline * 100) if baseline is not None else None,
            "edge_pct": _r(edge * 100) if edge is not None else None,
            "ci_pct": [_r(ci[0] * 100), _r(ci[1] * 100)] if ci else None,
            "hit_rate": _r(float((values > 0).mean())) if values.size else None,
            "baseline_hit_rate": _r(base_hit),
        })

    favourable, adverse = [], []
    for i, d in usable:
        if i + EXCURSION_BARS >= hi or i + 1 < ATR_BARS:
            continue
        unit = atr(candles[i + 1 - ATR_BARS: i + 1])
        if unit <= 0:
            continue
        top = float(highs[i + 1: i + 1 + EXCURSION_BARS].max())
        bottom = float(lows[i + 1: i + 1 + EXCURSION_BARS].min())
        up, down = (top - closes[i]) / unit, (closes[i] - bottom) / unit
        favourable.append(up if d == 1 else down)
        adverse.append(down if d == 1 else up)

    headline = next(x for x in horizons if x["h"] == HEADLINE_HORIZON)
    flags = []
    if len(usable) < MIN_SIGNALS:
        flags.append("too_few_signals")
    ci = headline["ci_pct"]
    if ci is None or ci[0] is None or ci[1] is None or ci[0] <= 0 <= ci[1]:
        flags.append("no_edge_detected")

    return {
        "from": int(candles[lo]["time"]) if hi > lo else None,
        "to": int(candles[hi - 1]["time"]) if hi > lo else None,
        "bars": hi - lo,
        "signals": len(usable),
        "skipped_neutral": skipped,
        "long_share": _r(long_share) if usable else None,
        "horizons": horizons,
        "mfe_atr": _r(float(np.mean(favourable))) if favourable else None,
        "mae_atr": _r(float(np.mean(adverse))) if adverse else None,
        "flags": flags,
    }


def study(
    candles: Sequence[Dict[str, Any]],
    signals: Sequence[TapeSignal],
    *,
    start: int,
    split: int,
    end: int,
    neutral: str,
) -> Dict[str, Any]:
    return {
        "seen": period_study(candles, signals, start, split, neutral),
        "unseen": period_study(candles, signals, split, end, neutral),
    }
