"""
Liquidity level detection.

A level is a price the market kept returning to. We find them by clustering the
highs and lows of the candles under consideration, then decide each one's role
from where it sits relative to the current price: everything below spot is
support, everything above is resistance. Role is not a property of whether the
level came from a high or a low - once price breaks through an old high, that
high becomes support.
"""
from typing import Any, Dict, List, Optional


# Prices within this fraction of each other are treated as the same level.
DEFAULT_SENSITIVITY = 0.02

# Sensitivity has to scale with the window, not be a fixed percentage. A
# thousand 1m candles span a fraction of a percent, so a flat 2% tolerance
# swallows the entire range into one band and every level lands on the same
# side of spot - support comes back empty. A thousand 1d candles span far more
# than 2% and the same flat figure merges levels that are nothing alike.
#
# Deriving the tolerance from the window's own height keeps roughly this many
# distinguishable bands on screen whatever the timeframe.
TARGET_BANDS = 12
MIN_SENSITIVITY = 0.0004
MAX_SENSITIVITY = 0.02

# Strength as a share of the candles analysed, so it means the same thing
# whether the window holds 60 candles or 600.
STRONG_SHARE = 0.40
MEDIUM_SHARE = 0.15

MAX_LEVELS_PER_SIDE = 5


def find_price_clusters(
    prices: List[float],
    sensitivity: float = DEFAULT_SENSITIVITY,
) -> List[Dict[str, Any]]:
    """
    Group nearby prices into levels.

    Returns one entry per cluster with its average price and how many prices
    landed in it. That count is the level's evidence and is carried through to
    the caller - discarding it would leave strength with nothing to measure.
    """
    if not prices:
        return []

    clusters: Dict[float, List[float]] = {}

    for price in prices:
        price = float(price)
        for key in clusters:
            if abs(price - key) / key <= sensitivity:
                clusters[key].append(price)
                break
        else:
            clusters[price] = [price]

    return [
        {"price": sum(members) / len(members), "test_count": len(members)}
        for members in clusters.values()
        if len(members) >= 2  # a price touched once is not a level
    ]


def adaptive_sensitivity(highs: List[float], lows: List[float]) -> float:
    """
    Clustering tolerance derived from how tall the window actually is.

    Returns a fraction of price, clamped so a flat window cannot collapse the
    tolerance to zero and a wildly volatile one cannot merge everything.
    """
    if not highs or not lows:
        return DEFAULT_SENSITIVITY

    hi, lo = max(highs), min(lows)
    mid = (hi + lo) / 2
    if mid <= 0:
        return DEFAULT_SENSITIVITY

    span = (hi - lo) / mid
    return min(MAX_SENSITIVITY, max(MIN_SENSITIVITY, span / TARGET_BANDS))


def _strength(test_count: int, sample_size: int) -> str:
    share = test_count / sample_size if sample_size else 0
    if share >= STRONG_SHARE:
        return "strong"
    if share >= MEDIUM_SHARE:
        return "medium"
    return "weak"


def detect_levels(
    candles: List[Dict[str, Any]],
    sensitivity: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Support and resistance for a set of candles, nearest to spot first.

    Sensitivity defaults to one derived from the window's own height, which is
    what makes the same detector work on a 1m and a 1d chart. Pass a value to
    override it.

    An empty or single-candle window yields empty results rather than an error;
    the caller clears its overlay.
    """
    if len(candles) < 2:
        return {
            "support_levels": [],
            "resistance_levels": [],
            "current_price": float(candles[-1]["close"]) if candles else 0.0,
            "sample_size": len(candles),
        }

    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    current_price = float(candles[-1]["close"])
    sample_size = len(candles)

    if sensitivity is None:
        sensitivity = adaptive_sensitivity(highs, lows)

    # Cluster highs and lows separately: pooling them lets one tolerance band
    # swallow distinct levels into a single wide one.
    clusters = find_price_clusters(highs, sensitivity)
    clusters += find_price_clusters(lows, sensitivity)

    def describe(cluster: Dict[str, Any]) -> Dict[str, Any]:
        price = float(cluster["price"])
        test_count = int(cluster["test_count"])
        return {
            "price": price,
            "strength": _strength(test_count, sample_size),
            "test_count": test_count,
            "distance_pct": round(abs(current_price - price) / current_price * 100, 2)
            if current_price
            else 0.0,
        }

    support = [describe(c) for c in clusters if c["price"] < current_price]
    resistance = [describe(c) for c in clusters if c["price"] >= current_price]

    # Nearest levels first - those are the ones price interacts with next.
    support.sort(key=lambda lvl: current_price - lvl["price"])
    resistance.sort(key=lambda lvl: lvl["price"] - current_price)

    return {
        "support_levels": support[:MAX_LEVELS_PER_SIDE],
        "resistance_levels": resistance[:MAX_LEVELS_PER_SIDE],
        "current_price": current_price,
        "sample_size": sample_size,
    }
