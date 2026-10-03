"""Coverage: what history exists, with gaps counted, cached briefly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers import history_controller as hc

H = 3_600_000


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, expiration=None):
        self.store[key] = value
        return True


async def test_coverage_counts_gaps_and_caches(monkeypatch):
    calls = []

    async def coverage():
        calls.append(1)
        return [{"symbol": "BTCUSDT", "timeframe": "1h", "first": 0, "last": 9 * H, "bars": 8}]

    cache = FakeCache()
    monkeypatch.setattr(hc.HistoryRepository, "coverage", staticmethod(coverage))
    monkeypatch.setattr(hc, "cache_service", cache)

    body = await hc.get_coverage()
    assert body["series"] == [
        {"symbol": "BTCUSDT", "timeframe": "1h", "first": 0, "last": 9 * H, "bars": 8, "gaps": 2}
    ]
    assert body["depth_days"]["1h"] == 1095 and body["depth_days"]["1d"] is None

    again = await hc.get_coverage()
    assert again == body and len(calls) == 1
