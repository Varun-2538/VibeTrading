"""
The scene: everything the detectors can see in one chart window, as a compact
document for a language model to read.

This is the whole of how the assistant "sees" the chart. It never gets pixels;
it gets this. Every price and bar time in here comes from a detector that ran
over exactly the candles on screen, so anything the model says back can be
checked against it - and anything it asks to mark can be refused if it is not
in here. Pure and deterministic: the same candles produce byte-identical JSON.

Kept small on purpose. The free-tier model budget is a few thousand tokens per
question and the scene has to leave room for the question, the history and the
answer. Every list is capped and every float rounded.
"""
from typing import Any, Dict, List, Sequence

import numpy as np

from analysis import candles as candle_shapes
from analysis import indicators
from analysis.levels import detect_levels
from analysis.patterns_big import detect_all_patterns
from analysis import structure as market_structure

# List caps. Raising these costs tokens on every question.
MAX_LEVELS_PER_SIDE = 5
MAX_PATTERNS = 4
MAX_SHAPES = 6
MAX_CROSSES = 3
LAST_BARS = 5
MAX_SWINGS = 6
MAX_EVENTS = 6

# Recent events per new indicator. Two is enough to say "again, and before
# that"; more is tokens for nothing.
MAX_INDICATOR_EVENTS = 2

# How far back an indicator cross still counts as "recent", in bars.
RECENT_BARS = 12

# Things a trader may ask about that no detector here can see. Listed so the
# model can say so by name instead of improvising.
UNSUPPORTED = (
    "open_interest",
    "funding_rate",
    "long_short_ratio",
    "short_covering",
    "long_unwinding",
    "order_flow",
    "volume_profile",
)

# What the model may talk about. Grows as detectors are added.
VOCABULARY = {
    "levels": ["support", "resistance"],
    "patterns": [
        "W (double bottom)", "M (double top)",
        "HS (head and shoulders)", "IHS (inverse head and shoulders)", "CUP (cup and handle)",
    ],
    "candles": list(candle_shapes.SHAPES),
    "indicators": [
        "rsi", "ema", "macd", "stochastic", "bollinger (and squeeze)",
        "vwap", "volume spike", "atr expansion",
    ],
    "structure": [
        "trend (HH/HL, LH/LL swings)",
        "breakout", "liquidity sweep", "rejection", "pullback",
    ],
}


def _r(value: float, places: int = 2) -> float:
    return float(round(float(value), places))


def _price_places(price: float) -> int:
    """Enough decimals to be meaningful without spending tokens on noise."""
    if price >= 1000:
        return 1
    if price >= 10:
        return 2
    if price >= 1:
        return 3
    return 5


def _levels(candles: Sequence[Dict[str, Any]], places: int) -> Dict[str, List[Dict[str, Any]]]:
    found = detect_levels(list(candles))
    out: Dict[str, List[Dict[str, Any]]] = {}
    for side in ("support", "resistance"):
        out[side] = [
            {
                "price": _r(level["price"], places),
                "strength": level["strength"],
                "tests": int(level.get("test_count", 0)),
            }
            for level in found.get(f"{side}_levels", [])[:MAX_LEVELS_PER_SIDE]
        ]
    return out


def _patterns(
    candles: Sequence[Dict[str, Any]],
    strictness: str,
    source: str,
    scale: str,
    places: int,
) -> List[Dict[str, Any]]:
    found = detect_all_patterns(
        list(candles),
        strictness=strictness,
        source=source,
        scale=scale,
        max_results=None,
    )
    # Biggest first: asked for "the W", a person means the one that stands out on
    # screen, not the newest wiggle at the right edge. And one per stretch of the
    # chart: a W nested inside a bigger W is the same W to the eye, and three of
    # them would fill the list while a clear one elsewhere is left out.
    # W and M before the larger shapes: they are what gets asked about by name.
    found.sort(key=lambda p: (p["kind"] not in ("W", "M"), -abs(p["neckline"] - p["target"])))
    span = lambda p: (min(pt["index"] for pt in p["points"].values()), max(pt["index"] for pt in p["points"].values()))
    kept: List[Dict[str, Any]] = []
    for p in found:
        a, b = span(p)
        same = [q for q in kept if q["kind"] == p["kind"]]
        if len(same) >= 2 or any(min(b, span(q)[1]) > max(a, span(q)[0]) for q in same):
            continue
        kept.append(p)
    found = kept[:MAX_PATTERNS]
    out = []
    for p in found:
        out.append(
            {
                "kind": p["kind"],
                "state": p["state"],
                "confidence": _r(p["confidence"], 0),
                "points": {
                    name: {"t": int(pt["time"]), "price": _r(pt["price"], places)}
                    for name, pt in p["points"].items()
                },
                "neckline": _r(p["neckline"], places),
                "target": _r(p["target"], places),
            }
        )
    return out


def _shapes(candles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Newest first, so the cap keeps what a trader would look at first."""
    out: List[Dict[str, Any]] = []
    for shape, mask in candle_shapes.shape_masks(candles).items():
        for i in np.flatnonzero(mask):
            out.append({"shape": shape, "t": int(candles[i]["time"])})
    out.sort(key=lambda s: s["t"], reverse=True)
    return out[:MAX_SHAPES]


def _recent_crosses(
    series: np.ndarray,
    levels: Sequence[float],
    times: Sequence[int],
) -> List[Dict[str, Any]]:
    out = []
    start = max(0, len(series) - RECENT_BARS)
    for level in levels:
        for direction in ("above", "below"):
            mask = indicators.crosses(series, level, direction)
            for i in np.flatnonzero(mask[start:]) + start:
                out.append({"level": level, "dir": direction, "t": int(times[i])})
    out.sort(key=lambda c: c["t"], reverse=True)
    return out[:MAX_CROSSES]


def _indicators(candles: Sequence[Dict[str, Any]], places: int) -> Dict[str, Any]:
    closes = np.array([float(c["close"]) for c in candles], dtype=float)
    times = [int(c["time"]) for c in candles]
    out: Dict[str, Any] = {}

    rsi = indicators.rsi(closes, 14)
    if len(rsi) >= 2 and not np.isnan(rsi[-1]):
        out["rsi"] = {
            "period": 14,
            "now": _r(rsi[-1], 1),
            "prev": _r(rsi[-2], 1) if not np.isnan(rsi[-2]) else None,
            "recent_crosses": _recent_crosses(rsi, (30, 50, 70), times),
        }

    ema20 = indicators.ema(closes, 20)
    ema50 = indicators.ema(closes, 50)
    if not np.isnan(ema20[-1]):
        ema: Dict[str, Any] = {"20": _r(ema20[-1], places)}
        if not np.isnan(ema50[-1]):
            ema["50"] = _r(ema50[-1], places)
            ema["stack"] = "bullish" if ema20[-1] > ema50[-1] else "bearish"
            # Where the fast line last crossed the slow one, if recently.
            cross = _recent_crosses(ema20 - ema50, (0.0,), times)
            if cross:
                ema["recent_cross"] = {
                    "dir": "bullish" if cross[0]["dir"] == "above" else "bearish",
                    "t": cross[0]["t"],
                }
        out["ema"] = ema

    line, signal, hist = indicators.macd(closes)
    if not np.isnan(line[-1]) and not np.isnan(signal[-1]):
        macd: Dict[str, Any] = {
            "line": _r(line[-1], places),
            "signal": _r(signal[-1], places),
            "hist": _r(hist[-1], places),
        }
        cross = _recent_crosses(hist, (0.0,), times)
        if cross:
            macd["recent_cross"] = {
                "dir": "bullish" if cross[0]["dir"] == "above" else "bearish",
                "t": cross[0]["t"],
            }
        out["macd"] = macd

    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)
    volumes = np.array([float(c["volume"]) for c in candles], dtype=float)
    bar_times = np.array(times, dtype=np.int64)

    def recent(mask: np.ndarray) -> List[int]:
        """Bar times where `mask` is true inside the recent window, newest last."""
        if mask.size == 0:
            return []
        start = max(0, mask.size - RECENT_BARS)
        hits = [int(times[i]) for i in np.flatnonzero(mask[start:]) + start]
        return hits[-MAX_INDICATOR_EVENTS:]

    k_line, d_line = indicators.stochastic(highs, lows, closes)
    if not np.isnan(k_line[-1]):
        k_now = float(k_line[-1])
        stoch: Dict[str, Any] = {
            "k": _r(k_now, 1),
            "state": "overbought" if k_now >= 80 else "oversold" if k_now <= 20 else "middle",
            "recent_crosses": [],
        }
        if not np.isnan(d_line[-1]):
            stoch["d"] = _r(d_line[-1], 1)
            for direction in ("above", "below"):
                for t in recent(indicators.crosses_series(k_line, d_line, direction)):
                    stoch["recent_crosses"].append({"level": "d", "dir": direction, "t": t})
        for level in (20, 80):
            for direction in ("above", "below"):
                for t in recent(indicators.crosses(k_line, float(level), direction)):
                    stoch["recent_crosses"].append({"level": level, "dir": direction, "t": t})
        stoch["recent_crosses"] = sorted(stoch["recent_crosses"], key=lambda c: c["t"], reverse=True)[:MAX_INDICATOR_EVENTS]
        out["stoch"] = stoch

    middle, upper, lower, width = indicators.bollinger(closes)
    if not np.isnan(upper[-1]):
        tightest = indicators.rolling_min(width, 120)
        bands: Dict[str, Any] = {
            "upper": _r(upper[-1], places),
            "lower": _r(lower[-1], places),
            "width": _r(width[-1], 4),
            # The coiled-spring setup: bandwidth at its tightest in 120 bars.
            "squeeze": bool(not np.isnan(width[-1]) and width[-1] <= tightest[-1]),
            "recent_crosses": [],
        }
        for band, series in (("upper", upper), ("lower", lower)):
            for direction in ("above", "below"):
                for t in recent(indicators.crosses_series(closes, series, direction)):
                    bands["recent_crosses"].append({"band": band, "dir": direction, "t": t})
        bands["recent_crosses"] = sorted(bands["recent_crosses"], key=lambda c: c["t"], reverse=True)[:MAX_INDICATOR_EVENTS]
        out["bollinger"] = bands

    vwap_line = indicators.vwap(highs, lows, closes, volumes, bar_times, anchor="day")
    if not np.isnan(vwap_line[-1]):
        vwap_block: Dict[str, Any] = {
            "anchor": "day",
            "value": _r(vwap_line[-1], places),
            "side": "above" if closes[-1] >= vwap_line[-1] else "below",
            "recent_crosses": [],
        }
        for direction in ("above", "below"):
            for t in recent(indicators.crosses_series(closes, vwap_line, direction)):
                vwap_block["recent_crosses"].append({"dir": direction, "t": t})
        vwap_block["recent_crosses"] = sorted(vwap_block["recent_crosses"], key=lambda c: c["t"], reverse=True)[:MAX_INDICATOR_EVENTS]
        out["vwap"] = vwap_block

    ratio = indicators.volume_ratio(volumes)
    if not np.isnan(ratio[-1]):
        with np.errstate(invalid="ignore"):
            spikes = np.nan_to_num(ratio, nan=0.0) >= 2.0
        out["volume"] = {"ratio": _r(ratio[-1], 2), "spikes": recent(spikes)}

    ranges = indicators.true_range(highs, lows, closes)
    unit = indicators.atr_series(highs, lows, closes)
    if not np.isnan(unit[-1]):
        with np.errstate(invalid="ignore"):
            wide = np.nan_to_num(ranges, nan=0.0) >= 2.0 * np.nan_to_num(unit, nan=np.inf)
        out["atr"] = {
            "value": _r(unit[-1], places),
            "expansion": bool(wide[-1]),
            "recent": recent(wide),
        }

    return out


def _structure(candles: Sequence[Dict[str, Any]], places: int) -> Dict[str, Any]:
    """Swings, the trend they imply, recent level events, and any pullback now."""
    sw = market_structure.swings(candles)
    pts = [
        {"label": p["label"], "t": p["t"], "price": _r(p["price"], places)}
        for p in sw["points"][-MAX_SWINGS:]
    ]
    events = [
        {"event": e["event"], "side": e["side"], "level": _r(e["level"], places), "t": e["t"]}
        for e in market_structure.recent_events(candles, RECENT_BARS)[:MAX_EVENTS]
    ]
    pb = market_structure.pullback(candles, sw)
    return {
        "trend": sw["trend"],
        "swings": pts,
        "events": events,
        "pullback": (
            {
                "side": pb["side"],
                "retrace": pb["retrace"],
                "holds": {"label": pb["holds"]["label"], "price": _r(pb["holds"]["price"], places), "t": pb["holds"]["t"]},
            }
            if pb
            else None
        ),
    }


def empty_scene(symbol: str, timeframe: str) -> Dict[str, Any]:
    """A valid scene for a window with nothing in it."""
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "window": {"from": None, "to": None, "bars": 0},
        "price": None,
        "levels": {"support": [], "resistance": []},
        "patterns": [],
        "candles": {"last": [], "shapes": []},
        "indicators": {},
        "structure": {},
        "vocabulary": VOCABULARY,
        "unsupported": list(UNSUPPORTED),
    }


def build_scene(
    candles: Sequence[Dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
    strictness: str = "balanced",
    source: str = "wick",
    scale: str = "swing",
) -> Dict[str, Any]:
    """
    Everything the detectors see in `candles`, which must already be windowed
    to what is on screen. Empty input yields an empty-but-valid scene rather
    than an error, so the model can say "nothing on screen".
    """
    if not candles:
        return empty_scene(symbol, timeframe)

    last = float(candles[-1]["close"])
    first = float(candles[0]["open"])
    places = _price_places(last)
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "window": {
            "from": int(candles[0]["time"]),
            "to": int(candles[-1]["time"]),
            "bars": len(candles),
        },
        "price": {
            "last": _r(last, places),
            "window_high": _r(max(highs), places),
            "window_low": _r(min(lows), places),
            "change_pct": _r((last - first) / first * 100.0, 2) if first else 0.0,
        },
        "levels": _levels(candles, places),
        "patterns": _patterns(candles, strictness, source, scale, places),
        "candles": {
            "last": [
                {
                    "t": int(c["time"]),
                    "o": _r(c["open"], places),
                    "h": _r(c["high"], places),
                    "l": _r(c["low"], places),
                    "c": _r(c["close"], places),
                }
                for c in candles[-LAST_BARS:]
            ],
            "shapes": _shapes(candles),
        },
        "indicators": _indicators(candles, places),
        "structure": _structure(candles, places),
        "vocabulary": VOCABULARY,
        "unsupported": list(UNSUPPORTED),
    }
