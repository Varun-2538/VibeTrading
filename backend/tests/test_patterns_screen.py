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
    candles = _bars([(0, 104), (10, 110), (20, 100), (30, 106), (40, 101), (55, 112)])
    ws = [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"]
    assert any(abs(w["points"]["low1"]["index"] - 20) <= 2 and abs(w["points"]["low2"]["index"] - 40) <= 2 for w in ws)


def test_a_deeper_low_in_the_middle_is_not_this_w():
    candles = _bars([(0, 108), (8, 100), (13, 104), (18, 97), (23, 104), (28, 100.3), (40, 110)])
    ws = [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"]
    assert not any(abs(w["points"]["low1"]["index"] - 8) <= 2 and abs(w["points"]["low2"]["index"] - 28) <= 2 for w in ws)


def test_a_w_whose_first_arm_is_no_taller_than_its_middle_is_not_one():
    # Falls from 106 to 100, back to 106, down to 100, out: the break of 106
    # leaves no room to the arm's top, so there is no trade in it.
    candles = _bars([(0, 106), (10, 100), (20, 106), (30, 100), (45, 112)])
    assert [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"] == []


def test_a_w_that_never_breaks_its_neckline_stops_being_one():
    # Lows ten bars apart, then sixty bars of drifting under the neckline.
    candles = _bars([(0, 110), (10, 100), (15, 106), (20, 100), (80, 104)])
    assert [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"] == []


def test_a_w_that_breaks_but_never_reaches_its_target_expires():
    # Breaks the neckline, stalls short of the arm's top for a hundred candles.
    candles = _bars([(0, 104), (10, 110), (20, 100), (30, 106), (40, 101), (48, 107.5), (150, 107)])
    assert [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"] == []


def test_a_w_that_reaches_its_target_in_time_stays():
    candles = _bars([(0, 104), (10, 110), (20, 100), (30, 106), (40, 101), (52, 112), (150, 111)])
    ws = [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"]
    assert ws and ws[0]["state"] == "confirmed" and ws[0]["target_hit"] is True


def test_the_target_is_the_top_of_the_first_arm():
    candles = _bars([(0, 104), (10, 110), (20, 100), (30, 106), (40, 101), (55, 112)])
    ws = [p for p in detect_double_patterns(candles, max_results=None) if p["kind"] == "W"]
    assert ws and abs(ws[0]["target"] - 110.05) < 0.2
