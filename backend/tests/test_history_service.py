"""History store: depths, parsing, gap counting, paging, resume, retry."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import history_service as hs

DAY = 86_400_000
NOW = 1_780_000_000_000  # fixed "now" for every test


def kline(open_ms, step_ms, price=100.0):
    """A Binance kline row: strings for prices, close time = open + step - 1."""
    return [
        open_ms, str(price), str(price + 2), str(price - 2), str(price + 1), "12.5",
        open_ms + step_ms - 1, "0", 0, "0", "0", "0",
    ]


def test_depths_match_the_spec():
    assert hs.HISTORY_DEPTH_DAYS == {"5m": 183, "15m": 365, "1h": 1095, "1d": None}
    assert set(hs.TIMEFRAME_MS) == set(hs.HISTORY_DEPTH_DAYS)
    assert len(hs.PAIRS) == 9


def test_depth_start_is_aligned_to_the_timeframe():
    start = hs.depth_start_ms("1h", NOW)
    assert start % hs.TIMEFRAME_MS["1h"] == 0
    assert NOW - start >= 1095 * DAY
    assert NOW - start < 1095 * DAY + hs.TIMEFRAME_MS["1h"]


def test_unlimited_depth_starts_at_zero():
    assert hs.depth_start_ms("1d", NOW) == 0


def test_unknown_timeframe_is_refused():
    with pytest.raises(hs.UnknownHistoryTimeframe):
        hs.depth_start_ms("1m", NOW)


def test_parse_klines_coerces_and_keeps_only_closed_bars():
    step = hs.TIMEFRAME_MS["1h"]
    last_open = NOW - (NOW % step)  # the bar still forming at NOW
    rows = [kline(last_open - step, step), kline(last_open, step)]
    candles = hs.parse_klines(rows, NOW)
    assert candles == [{
        "time": last_open - step, "open": 100.0, "high": 102.0, "low": 98.0,
        "close": 101.0, "volume": 12.5,
    }]


def test_missing_bars_counts_holes_between_first_and_last():
    step = hs.TIMEFRAME_MS["15m"]
    assert hs.missing_bars(0, 9 * step, 10, "15m") == 0
    assert hs.missing_bars(0, 9 * step, 7, "15m") == 3
    assert hs.missing_bars(0, 0, 0, "15m") == 0


from datetime import datetime, timezone

from repositories import history_repository as hr


def test_row_round_trip_keeps_ms_and_utc():
    candle = {"time": 1_700_000_000_000, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9.0}
    row = hr.to_row("btcusdt", "1h", candle)
    assert row[0] == "BTCUSDT" and row[1] == "1h"
    assert row[2] == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    record = {"time": row[2], "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 9.0}
    assert hr.from_record(record) == candle


def test_ms_conversion_is_exact_for_whole_seconds():
    assert hr.dt_to_ms(hr.ms_to_dt(1_780_000_000_000)) == 1_780_000_000_000


import httpx


class StubClient:
    """Replays a list of (status, json, headers) responses and records params."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append(params)
        status, body, headers = self.responses.pop(0)
        return httpx.Response(status, json=body, headers=headers, request=httpx.Request("GET", url))


async def no_sleep(_seconds):
    no_sleep.slept.append(_seconds)


no_sleep.slept = []


async def test_fetch_page_requests_the_right_window_and_parses():
    step = hs.TIMEFRAME_MS["1h"]
    start = NOW - 10 * step - (NOW % step)
    client = StubClient([(200, [kline(start, step)], {})])
    candles = await hs.fetch_page(client, "btcusdt", "1h", start, now_ms=NOW, sleep=no_sleep)
    assert client.calls == [{"symbol": "BTCUSDT", "interval": "1h", "startTime": start, "limit": 1000}]
    assert [c["time"] for c in candles] == [start]


async def test_fetch_page_honours_retry_after_on_429():
    no_sleep.slept.clear()
    step = hs.TIMEFRAME_MS["1h"]
    start = NOW - 10 * step - (NOW % step)
    client = StubClient([
        (429, {"code": -1003}, {"Retry-After": "7"}),
        (200, [kline(start, step)], {}),
    ])
    candles = await hs.fetch_page(client, "BTCUSDT", "1h", start, now_ms=NOW, sleep=no_sleep)
    assert len(candles) == 1
    assert no_sleep.slept == [7.0]


async def test_fetch_page_backs_off_on_5xx_then_gives_up():
    no_sleep.slept.clear()
    client = StubClient([(502, {}, {})] * hs.MAX_ATTEMPTS)
    with pytest.raises(hs.HistoryFetchError):
        await hs.fetch_page(client, "BTCUSDT", "1h", 0, now_ms=NOW, sleep=no_sleep)
    assert len(client.calls) == hs.MAX_ATTEMPTS
    assert no_sleep.slept == sorted(no_sleep.slept) and no_sleep.slept[0] >= 1


async def test_fetch_page_does_not_retry_a_bad_request():
    client = StubClient([(400, {"code": -1121, "msg": "Invalid symbol."}, {})])
    with pytest.raises(hs.HistoryFetchError, match="400"):
        await hs.fetch_page(client, "NOPE", "1h", 0, now_ms=NOW, sleep=no_sleep)
    assert len(client.calls) == 1


class FakeRepo:
    def __init__(self, latest=None):
        self.latest = latest
        self.rows = {}
        self.trimmed = None

    async def latest_time(self, symbol, timeframe):
        return self.latest

    async def upsert(self, symbol, timeframe, candles):
        for c in candles:
            self.rows[c["time"]] = c
        return len(candles)

    async def trim(self, symbol, timeframe, before_ms):
        self.trimmed = before_ms
        self.rows = {t: c for t, c in self.rows.items() if t >= before_ms}


def fake_exchange(first_ms, step, now_ms, page=1000):
    """A fetch function serving contiguous bars from first_ms up to the last closed bar."""
    calls = []

    async def fetch(client, symbol, timeframe, start_ms, *, now_ms=now_ms, sleep=None):
        calls.append(start_ms)
        t = max(start_ms, first_ms)
        t += (-t) % step
        out = []
        while len(out) < page and t + step <= now_ms:
            out.append({"time": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
            t += step
        return out

    return fetch, calls


async def test_backfill_from_empty_assembles_contiguous_history():
    step = hs.TIMEFRAME_MS["1h"]
    start = hs.depth_start_ms("1h", NOW)
    fetch, calls = fake_exchange(start, step, NOW)
    repo = FakeRepo()
    result = await hs.backfill("BTCUSDT", "1h", client=None, now_ms=NOW, repo=repo, fetch=fetch, sleep=no_sleep)
    times = sorted(repo.rows)
    assert times[0] == start
    assert all(b - a == step for a, b in zip(times, times[1:]))
    assert times[-1] + step <= NOW
    assert result.bars == len(times) and result.pages == len(calls) and result.error is None
    assert calls[0] == start


async def test_backfill_resumes_after_the_newest_stored_bar():
    step = hs.TIMEFRAME_MS["1h"]
    last_closed_open = NOW - (NOW % step) - step
    stored = last_closed_open - 5 * step
    fetch, calls = fake_exchange(0, step, NOW)
    repo = FakeRepo(latest=stored)
    result = await hs.backfill("BTCUSDT", "1h", client=None, now_ms=NOW, repo=repo, fetch=fetch, sleep=no_sleep)
    assert calls == [stored + step]
    assert result.bars == 5


async def test_backfill_trims_below_the_depth():
    step = hs.TIMEFRAME_MS["5m"]
    fetch, _ = fake_exchange(0, step, NOW)
    repo = FakeRepo(latest=NOW - (NOW % step) - 2 * step)
    await hs.backfill("BTCUSDT", "5m", client=None, now_ms=NOW, repo=repo, fetch=fetch, sleep=no_sleep)
    assert repo.trimmed == hs.depth_start_ms("5m", NOW)


async def test_backfill_keeps_everything_for_daily():
    step = hs.TIMEFRAME_MS["1d"]
    fetch, calls = fake_exchange(1_500_000_000_000 - (1_500_000_000_000 % step), step, NOW)
    repo = FakeRepo()
    await hs.backfill("BTCUSDT", "1d", client=None, now_ms=NOW, repo=repo, fetch=fetch, sleep=no_sleep)
    assert calls[0] == 0
    assert repo.trimmed is None


async def test_backfill_keeps_pages_already_stored_when_a_later_page_fails():
    step = hs.TIMEFRAME_MS["1h"]
    good, _ = fake_exchange(hs.depth_start_ms("1h", NOW), step, NOW)
    pages = {"n": 0}

    async def flaky(client, symbol, timeframe, start_ms, *, now_ms, sleep=None):
        pages["n"] += 1
        if pages["n"] == 2:
            raise hs.HistoryFetchError("boom")
        return await good(client, symbol, timeframe, start_ms, now_ms=now_ms)

    repo = FakeRepo()
    result = await hs.backfill("BTCUSDT", "1h", client=None, now_ms=NOW, repo=repo, fetch=flaky, sleep=no_sleep)
    assert result.error == "boom"
    assert result.bars == 1000 and len(repo.rows) == 1000


async def test_backfill_stops_when_a_page_does_not_advance():
    step = hs.TIMEFRAME_MS["1h"]
    start = hs.depth_start_ms("1h", NOW)

    async def stuck(client, symbol, timeframe, start_ms, *, now_ms, sleep=None):
        stuck.calls += 1
        return [{"time": start, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}]

    stuck.calls = 0
    await hs.backfill("BTCUSDT", "1h", client=None, now_ms=NOW, repo=FakeRepo(), fetch=stuck, sleep=no_sleep)
    assert stuck.calls == 2
