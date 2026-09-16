"""Deterministic candle series for backtest tests."""
from typing import Dict, List

import numpy as np

H = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % H)


def random_walk(n: int, seed: int = 1, step_ms: int = H, vol: float = 0.006) -> List[Dict]:
    rng = np.random.default_rng(seed)
    closes = 60_000.0 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    out, prev = [], float(closes[0])
    for i, close in enumerate(closes):
        o, c = prev, float(close)
        hi = max(o, c) * (1 + abs(rng.normal(0, vol / 3)))
        lo = min(o, c) * (1 - abs(rng.normal(0, vol / 3)))
        out.append({"time": T0 + i * step_ms, "open": o, "high": hi, "low": lo, "close": c, "volume": 1.0})
        prev = c
    return out


def doji_series(n: int, every: int = 5, step_ms: int = H) -> List[Dict]:
    """Wide trending bars, with a textbook doji every `every` bars."""
    out, price = [], 100.0
    for i in range(n):
        if i % every == every - 1:
            o = c = price
            hi, lo = price + 2.0, price - 2.0
        else:
            o, c = price, price + 1.0
            hi, lo = c + 0.2, o - 0.2
            price = c
        out.append({"time": T0 + i * step_ms, "open": o, "high": hi, "low": lo, "close": c, "volume": 1.0})
    return out
