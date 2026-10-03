"""Replay: no look-ahead, and the same answer the live engine gives."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.replay import candidates_at, first_index, replay_range, tape_key
from models.rule_schemas import RuleCreate
from repositories.rule_repository import RuleEventRepository
from services.rule_decision import first_passing
from services.rule_engine import RuleEngine
from walks import H, doji_series, random_walk


def params_for(raw):
    return RuleCreate(name="t", symbol="BTCUSDT", timeframe="1h", params=raw).params.model_dump()


DOJI = params_for({"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}], "lookback": 60})
W = params_for({"agent": "pattern", "kinds": ["W", "M"], "states": ["forming", "approaching", "confirmed"],
                "min_confidence": 0, "lookback": 150})
NEAR_SUPPORT = params_for({"agent": "liquidity", "side": "support", "event": "approach",
                           "proximity_pct": 2.0, "min_strength": "weak", "lookback": 150})


@pytest.fixture(autouse=True)
def no_dedup_lookup(monkeypatch):
    async def never(_key):
        return False
    monkeypatch.setattr(RuleEventRepository, "exists", never)


def test_first_index_leaves_a_full_live_window():
    assert first_index(DOJI) == 58  # window of 59 bars ends at index 58


def test_doji_rule_finds_every_doji_after_warmup():
    candles = doji_series(200)
    rows = replay_range(candles, DOJI, first_index(DOJI), len(candles))
    assert [r[0] for r in rows] == [i for i in range(first_index(DOJI), 200) if i % 5 == 4]
    assert rows[0][1][0][1] == "neutral"


@pytest.mark.parametrize("params", [DOJI, W, NEAR_SUPPORT], ids=["sequence", "pattern", "liquidity"])
def test_no_look_ahead(params):
    candles = random_walk(260, seed=3) if params is not DOJI else doji_series(260)
    start = first_index(params)
    before = replay_range(candles, params, start, 230)
    future = [{**c, "time": c["time"] + 1000 * H, "high": c["high"] * 3, "low": c["low"] / 3}
              for c in random_walk(30, seed=99)]
    after = replay_range(candles[:230] + future, params, start, 230)
    assert before == after


@pytest.mark.parametrize("params", [DOJI, W, NEAR_SUPPORT], ids=["sequence", "pattern", "liquidity"])
async def test_parity_with_the_live_engine(params):
    candles = random_walk(260, seed=5) if params is not DOJI else doji_series(260)
    size = params["lookback"] - 1
    rule = {"id": "r", "owner_key": "o", "agent": params["agent"], "symbol": "BTCUSDT", "timeframe": "1h",
            "params": params, "persist_bars": 0, "cooldown_secs": 0, "pending": None,
            "last_candle_time": None, "last_fired_at": None}
    for i in range(first_index(params), 260, 7):
        window = candles[i + 1 - size: i + 1]
        live, _ = await RuleEngine.evaluate_rule(rule, window, dry_run=True)
        replayed = first_passing(params["agent"], params, candidates_at(candles, i, params))
        assert (live.identity if live else None) == (replayed.identity if replayed else None), i


def test_tape_key_ignores_filters_but_not_detector_settings():
    base = tape_key("BTCUSDT", "1h", W, 123)
    assert tape_key("btcusdt", "1h", {**W, "min_confidence": 80}, 123) == base
    assert tape_key("BTCUSDT", "1h", {**W, "strictness": "strict"}, 123) != base
    assert tape_key("BTCUSDT", "1h", {**W, "lookback": 200}, 123) != base
    assert tape_key("BTCUSDT", "1h", W, 124) != base
    assert tape_key("BTCUSDT", "1h", {**NEAR_SUPPORT, "proximity_pct": 1.0}, 123) != tape_key("BTCUSDT", "1h", NEAR_SUPPORT, 123)
