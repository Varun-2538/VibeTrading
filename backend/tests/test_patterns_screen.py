"""A W a person would circle on a quiet chart: lows a dollar apart, six deep."""
from analysis.patterns import detect_double_patterns


def _bars(path):
    """Line segments through (bar, price) knots, a little wick either side."""
    prices = []
    for (i0, p0), (i1, p1) in zip(path, path[1:]):
        for i in range(i0, i1):
            prices.append(p0 + (p1 - p0) * (i - i0) / (i1 - i0))
    prices.append(path[-1][1])
    return [
        {"time": i * 60_000, "open": p, "high": p + 0.05, "low": p - 0.05, "close": p}
        for i, p in enumerate(prices)
    ]


def test_lows_apart_by_more_than_atr_but_little_against_the_height():
    # ATR here is about a third of a dollar; the lows are a dollar apart and the
    # W is six dollars deep, so against itself it is a match.
    candles = _bars([(0, 104), (30, 106), (60, 100), (90, 106), (120, 101), (160, 110)])
    ws = [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"]
    assert any(abs(w["points"]["low1"]["index"] - 60) <= 2 and abs(w["points"]["low2"]["index"] - 120) <= 2 for w in ws)


def test_a_deeper_low_in_the_middle_is_not_this_w():
    candles = _bars([(0, 106), (30, 100), (45, 104), (60, 97), (75, 104), (90, 100.3), (130, 110)])
    ws = [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"]
    assert not any(abs(w["points"]["low1"]["index"] - 30) <= 2 and abs(w["points"]["low2"]["index"] - 90) <= 2 for w in ws)
