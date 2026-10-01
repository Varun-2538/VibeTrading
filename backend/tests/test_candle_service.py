"""CandleService: interval mapping, caching, windowing, failure handling."""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import candle_service as cs_module
from services.candle_service import (
    CandleFetchError,
    CandleService,
    UnknownTimeframe,
)


class FakeCache:
    """Stands in for Redis. `broken=True` simulates Redis being unavailable."""

    def __init__(self, broken=False):
        self.store = {}
        self.broken = broken
        self.reads = 0
        self.writes = 0

    async def get(self, key):
        self.reads += 1
        if self.broken:
            return None
        return self.store.get(key)

    async def set(self, key, value, expiration=None):
        self.writes += 1
        if self.broken:
            return False
        self.store[key] = value
        return True


def kline(open_time, price):
    # Binance returns strings; the service must coerce them.
    return [open_time, str(price), str(price + 1), str(price - 1), str(price), "10.5"]


@pytest.fixture(autouse=True)
def reset_shared_client():
    """
    The service keeps one client for the process. Clear it around every test
    so each one builds its own stub instead of reusing a previous test's.
    """
    cs_module._client = None
    yield
    cs_module._client = None


@pytest.fixture
def cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(cs_module, "cache_service", fake)
    return fake


def stub_binance(monkeypatch, rows, spy=None):
    class StubClient:
        is_closed = False

        def __init__(self, *a, **k):
            pass

        async def get(self, url, params=None):
            if spy is not None:
                spy.append(params)
            request = httpx.Request("GET", url)
            return httpx.Response(200, json=rows, request=request)

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(cs_module.httpx, "AsyncClient", StubClient)


class TestGetCandles:
    @pytest.mark.asyncio
    async def test_parses_binance_rows_into_candles(self, cache, monkeypatch):
        stub_binance(monkeypatch, [kline(1_700_000_000_000, 100)])

        candles = await CandleService.get_candles("btcusdt", "1h", 1)

        assert candles == [
            {
                "time": 1_700_000_000_000,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 10.5,
            }
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1h", "1d"])
    async def test_every_supported_timeframe_reaches_binance_unchanged(
        self, cache, monkeypatch, timeframe
    ):
        calls = []
        stub_binance(monkeypatch, [kline(1, 10)], spy=calls)

        await CandleService.get_candles("BTCUSDT", timeframe, 5)

        assert calls[0]["interval"] == timeframe

    @pytest.mark.asyncio
    async def test_unknown_timeframe_is_rejected(self, cache):
        with pytest.raises(UnknownTimeframe):
            await CandleService.get_candles("BTCUSDT", "7s", 10)

    @pytest.mark.asyncio
    async def test_second_call_is_served_from_cache(self, cache, monkeypatch):
        calls = []
        stub_binance(monkeypatch, [kline(1, 10)], spy=calls)

        await CandleService.get_candles("BTCUSDT", "1h", 5)
        await CandleService.get_candles("BTCUSDT", "1h", 5)

        assert len(calls) == 1, "the second call should not hit Binance"

    @pytest.mark.asyncio
    async def test_symbol_case_does_not_split_the_cache(self, cache, monkeypatch):
        calls = []
        stub_binance(monkeypatch, [kline(1, 10)], spy=calls)

        await CandleService.get_candles("btcusdt", "1h", 5)
        await CandleService.get_candles("BTCUSDT", "1h", 5)

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_limit_is_clamped_to_binance_maximum(self, cache, monkeypatch):
        calls = []
        stub_binance(monkeypatch, [kline(1, 10)], spy=calls)

        await CandleService.get_candles("BTCUSDT", "1h", 99_999)

        assert calls[0]["limit"] == 1000

    @pytest.mark.asyncio
    async def test_still_returns_candles_when_redis_is_down(self, monkeypatch):
        monkeypatch.setattr(cs_module, "cache_service", FakeCache(broken=True))
        stub_binance(monkeypatch, [kline(1, 10)])

        candles = await CandleService.get_candles("BTCUSDT", "1h", 1)

        assert len(candles) == 1

    @pytest.mark.asyncio
    async def test_upstream_failure_raises_rather_than_returning_empty(
        self, cache, monkeypatch
    ):
        class FailingClient:
            is_closed = False

            def __init__(self, *a, **k):
                pass

            async def get(self, url, params=None):
                raise httpx.ConnectError("boom")

            async def aclose(self):
                self.is_closed = True

        monkeypatch.setattr(cs_module.httpx, "AsyncClient", FailingClient)

        with pytest.raises(CandleFetchError):
            await CandleService.get_candles("BTCUSDT", "1h", 1)


class TestSharedClient:
    @pytest.mark.asyncio
    async def test_client_is_reused_across_calls(self, cache, monkeypatch):
        """
        Regression: building a client per request cost a fresh SSL context and
        TLS handshake every time - about eight seconds a call on Windows, which
        read as a hung chart rather than a slow one.
        """
        built = []

        class CountingClient:
            is_closed = False

            def __init__(self, *a, **k):
                built.append(1)

            async def get(self, url, params=None):
                return httpx.Response(200, json=[kline(1, 10)], request=httpx.Request("GET", url))

            async def aclose(self):
                self.is_closed = True

        monkeypatch.setattr(cs_module.httpx, "AsyncClient", CountingClient)

        await CandleService.get_candles("BTCUSDT", "1h", 5)
        await CandleService.get_candles("ETHUSDT", "1h", 5)
        await CandleService.get_candles("SOLUSDT", "1h", 5)

        assert len(built) == 1, f"expected one shared client, built {len(built)}"


class TestWindow:
    CANDLES = [{"time": t, "close": 1.0} for t in (100, 200, 300, 400, 500)]

    def test_inclusive_bounds(self):
        got = CandleService.window(self.CANDLES, 200, 400)
        assert [c["time"] for c in got] == [200, 300, 400]

    def test_open_ended_sides(self):
        assert len(CandleService.window(self.CANDLES, None, 300)) == 3
        assert len(CandleService.window(self.CANDLES, 300, None)) == 3
        assert len(CandleService.window(self.CANDLES)) == 5

    def test_window_past_the_data_is_empty_not_an_error(self):
        assert CandleService.window(self.CANDLES, 10_000, 20_000) == []
