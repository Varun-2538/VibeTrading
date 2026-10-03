"""
Rule engine semantics over injected detector output - no network, no database.

Detector results are passed in rather than computed, so these tests pin the
engine's decisions (match, persistence, dedup identity) instead of re-testing
pattern and level detection, which have their own suites.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repositories.rule_repository import RuleEventRepository
from services.rule_engine import (
    BLOCKED_COOLDOWN,
    BLOCKED_DEDUP,
    BLOCKED_NO_MATCH,
    BLOCKED_PERSISTENCE,
    RuleEngine,
    Signal,
    _match_liquidity,
    _pattern_identity,
)


def candles(closes, start_ms=1_700_000_000_000, step_ms=60_000):
    return [
        {
            "time": start_ms + i * step_ms,
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": 1.0,
        }
        for i, c in enumerate(closes)
    ]


def pattern(kind="W", state="confirmed", confidence=80.0, times=(1000, 2000, 3000)):
    """A detector-shaped pattern. Point keys differ by kind, as in patterns.py."""
    if kind == "W":
        keys = ("low1", "peak", "low2")
    else:
        keys = ("high1", "trough", "high2")
    return {
        "kind": kind,
        "state": state,
        "confidence": confidence,
        "components": {"similarity": 90.0, "depth": 80.0, "symmetry": 70.0},
        "points": {k: {"time": t, "price": 100.0, "index": i}
                   for i, (k, t) in enumerate(zip(keys, times))},
        "neckline": 105.0,
        "target": 110.0,
    }


def rule(**overrides):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "owner_key": "22222222-2222-2222-2222-222222222222",
        "name": "test rule",
        "agent": "pattern",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "params": {
            "agent": "pattern",
            "kinds": ["W"],
            "states": ["confirmed"],
            "min_confidence": 70.0,
        },
        "action": {"kind": "alert"},
        "enabled": True,
        "cooldown_secs": 0,
        "persist_bars": 0,
        "pending": None,
        "last_candle_time": None,
        "last_fired_at": None,
        "fire_count": 0,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def no_dedup_lookup(monkeypatch):
    """Dry runs check the dedup table; keep that out of unit tests by default."""
    async def _never_exists(_key):
        return False

    monkeypatch.setattr(RuleEventRepository, "exists", _never_exists)


class TestPatternIdentity:
    def test_is_stable_for_the_same_setup(self):
        assert _pattern_identity(pattern()) == _pattern_identity(pattern())

    def test_reads_times_regardless_of_kind_specific_keys(self):
        # W uses low1/peak/low2 and M uses high1/trough/high2. Identity must not
        # depend on knowing which, or it silently breaks for one kind.
        assert "1000:2000:3000" in _pattern_identity(pattern(kind="W"))
        assert "1000:2000:3000" in _pattern_identity(pattern(kind="M"))

    def test_changes_when_the_state_advances(self):
        forming = _pattern_identity(pattern(state="forming"))
        confirmed = _pattern_identity(pattern(state="confirmed"))
        assert forming != confirmed

    def test_changes_when_the_pivots_move(self):
        assert _pattern_identity(pattern()) != _pattern_identity(
            pattern(times=(1000, 2000, 4000))
        )


class TestDedupKey:
    def _signal(self, candle_time, identity="W:1:2:3:confirmed"):
        return Signal(
            rule_id="r1",
            agent="pattern",
            symbol="BTCUSDT",
            timeframe="1h",
            candle_time=candle_time,
            identity=identity,
            direction="bullish",
            price=100.0,
            provisional=False,
        )

    def test_same_signal_on_same_bar_is_one_key(self):
        when = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert self._signal(when).dedup_key() == self._signal(when).dedup_key()

    def test_next_bar_is_a_new_key(self):
        first = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert self._signal(first).dedup_key() != self._signal(
            first + timedelta(hours=1)
        ).dedup_key()


class TestLiquidityMatching:
    def test_approach_fires_inside_the_proximity_band(self):
        levels = {
            "support_levels": [{"price": 99.0, "strength": "medium", "test_count": 5,
                                "distance_pct": 0.2}],
            "resistance_levels": [],
        }
        params = {"side": "support", "min_strength": "medium",
                  "event": "approach", "proximity_pct": 0.3}

        matched = _match_liquidity(params, levels, [100.0, 99.2])
        assert matched is not None
        assert matched[1] == "bullish"

    def test_approach_ignores_a_level_that_is_too_far(self):
        levels = {
            "support_levels": [{"price": 90.0, "strength": "strong", "test_count": 9,
                                "distance_pct": 10.0}],
            "resistance_levels": [],
        }
        params = {"side": "support", "min_strength": "weak",
                  "event": "approach", "proximity_pct": 0.3}

        assert _match_liquidity(params, levels, [100.0, 100.0]) is None

    def test_approach_respects_minimum_strength(self):
        levels = {
            "support_levels": [{"price": 99.9, "strength": "weak", "test_count": 2,
                                "distance_pct": 0.1}],
            "resistance_levels": [],
        }
        params = {"side": "support", "min_strength": "strong",
                  "event": "approach", "proximity_pct": 1.0}

        assert _match_liquidity(params, levels, [100.0, 99.95]) is None

    def test_support_break_is_found_even_though_the_level_reclassified(self):
        # Once price closes below a support, detect_levels reports that level as
        # resistance, because it sorts against the latest close. A break must
        # still be detected, so both lists are searched.
        levels = {
            "support_levels": [],
            "resistance_levels": [{"price": 100.0, "strength": "medium",
                                   "test_count": 6, "distance_pct": 1.0}],
        }
        params = {"side": "support", "min_strength": "medium", "event": "break",
                  "proximity_pct": 0.3}

        matched = _match_liquidity(params, levels, [101.0, 99.0])
        assert matched is not None
        assert matched[0] == "support:break:100"
        assert matched[1] == "bearish"

    def test_no_break_when_price_never_crossed(self):
        levels = {
            "support_levels": [{"price": 98.0, "strength": "medium",
                                "test_count": 6, "distance_pct": 2.0}],
            "resistance_levels": [],
        }
        params = {"side": "support", "min_strength": "medium", "event": "break",
                  "proximity_pct": 0.3}

        assert _match_liquidity(params, levels, [101.0, 100.0]) is None

    def test_resistance_break_is_bullish(self):
        levels = {
            "support_levels": [{"price": 100.0, "strength": "medium",
                                "test_count": 6, "distance_pct": 1.0}],
            "resistance_levels": [],
        }
        params = {"side": "resistance", "min_strength": "medium", "event": "break",
                  "proximity_pct": 0.3}

        matched = _match_liquidity(params, levels, [99.0, 101.0])
        assert matched is not None
        assert matched[1] == "bullish"


class TestEvaluateRule:
    async def test_confirmed_pattern_fires(self):
        signal, blocked = await RuleEngine.evaluate_rule(
            rule(), candles([100, 101]), patterns=[pattern()], dry_run=True
        )
        assert blocked is None
        assert signal is not None
        assert signal.direction == "bullish"
        assert signal.provisional is False

    async def test_forming_pattern_is_excluded_by_default(self):
        signal, blocked = await RuleEngine.evaluate_rule(
            rule(), candles([100, 101]),
            patterns=[pattern(state="forming")], dry_run=True
        )
        assert blocked == BLOCKED_NO_MATCH
        assert signal is None

    async def test_forming_pattern_is_marked_provisional_when_opted_into(self):
        opted_in = rule(params={
            "agent": "pattern", "kinds": ["W"],
            "states": ["forming"], "min_confidence": 0,
        })
        signal, blocked = await RuleEngine.evaluate_rule(
            opted_in, candles([100, 101]),
            patterns=[pattern(state="forming")], dry_run=True
        )
        assert blocked is None
        assert signal.provisional is True

    async def test_confidence_floor_is_enforced(self):
        signal, blocked = await RuleEngine.evaluate_rule(
            rule(), candles([100, 101]),
            patterns=[pattern(confidence=50.0)], dry_run=True
        )
        assert blocked == BLOCKED_NO_MATCH

    async def test_wrong_kind_does_not_match(self):
        signal, blocked = await RuleEngine.evaluate_rule(
            rule(), candles([100, 101]), patterns=[pattern(kind="M")], dry_run=True
        )
        assert blocked == BLOCKED_NO_MATCH

    async def test_persistence_blocks_the_first_observation(self):
        signal, blocked = await RuleEngine.evaluate_rule(
            rule(persist_bars=1), candles([100, 101]),
            patterns=[pattern()], dry_run=True
        )
        assert blocked == BLOCKED_PERSISTENCE
        assert signal is not None  # reported, but not fireable yet

    async def test_persistence_passes_once_the_setup_survives_a_close(self):
        identity = _pattern_identity(pattern())
        armed = rule(
            persist_bars=1,
            pending={"identity": identity, "seen": 1},
            last_candle_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        signal, blocked = await RuleEngine.evaluate_rule(
            armed, candles([100, 101]), patterns=[pattern()], dry_run=True
        )
        assert blocked is None

    async def test_a_different_setup_restarts_the_streak(self):
        armed = rule(
            persist_bars=1,
            pending={"identity": "W:9:9:9:confirmed", "seen": 1},
            last_candle_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        signal, blocked = await RuleEngine.evaluate_rule(
            armed, candles([100, 101]), patterns=[pattern()], dry_run=True
        )
        assert blocked == BLOCKED_PERSISTENCE

    async def test_cooldown_blocks_a_recent_refire(self):
        armed = rule(
            cooldown_secs=900,
            last_fired_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        signal, blocked = await RuleEngine.evaluate_rule(
            armed, candles([100, 101]), patterns=[pattern()], dry_run=True
        )
        assert blocked == BLOCKED_COOLDOWN

    async def test_cooldown_expires(self):
        armed = rule(
            cooldown_secs=60,
            last_fired_at=datetime.now(timezone.utc) - timedelta(seconds=600),
        )
        signal, blocked = await RuleEngine.evaluate_rule(
            armed, candles([100, 101]), patterns=[pattern()], dry_run=True
        )
        assert blocked is None

    async def test_an_already_fired_signal_reports_dedup(self, monkeypatch):
        async def _always_exists(_key):
            return True

        monkeypatch.setattr(RuleEventRepository, "exists", _always_exists)

        signal, blocked = await RuleEngine.evaluate_rule(
            rule(), candles([100, 101]), patterns=[pattern()], dry_run=True
        )
        assert blocked == BLOCKED_DEDUP

    async def test_too_few_candles_is_not_a_match(self):
        signal, blocked = await RuleEngine.evaluate_rule(
            rule(), candles([100]), patterns=[pattern()], dry_run=True
        )
        assert blocked == BLOCKED_NO_MATCH

    async def test_signal_price_is_the_last_closed_bar(self):
        signal, _ = await RuleEngine.evaluate_rule(
            rule(), candles([100, 123.5]), patterns=[pattern()], dry_run=True
        )
        assert signal.price == 123.5


# --- sequence rules ----------------------------------------------------------


def _sequence_rule(**over):
    base = {
        "id": "00000000-0000-0000-0000-00000000seq1",
        "owner_key": "0xabc",
        "agent": "sequence",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "params": {
            "agent": "sequence",
            "steps": [{"type": "candle", "shape": "doji", "max_body_pct": 10}],
            "within_bars": 3,
            "lookback": 300,
        },
        "persist_bars": 0,
        "cooldown_secs": 0,
        "pending": None,
        "last_candle_time": None,
        "last_fired_at": None,
    }
    base.update(over)
    return base


def _doji_bars(n, doji_last=True):
    out = candles([100.0 + i for i in range(n)])
    for c in out:
        c["open"] = c["close"] - 2.0
        c["high"] = c["close"] + 3.0
        c["low"] = c["open"] - 3.0
    if doji_last:
        out[-1]["open"] = out[-1]["close"] - 0.01
    return out


async def test_sequence_rule_fires_on_a_doji_closing_bar(monkeypatch):
    async def no_exists(_key):
        return False

    monkeypatch.setattr(RuleEventRepository, "exists", no_exists)
    signal, blocked = await RuleEngine.evaluate_rule(
        _sequence_rule(), _doji_bars(20), dry_run=True
    )
    assert blocked is None
    assert signal is not None
    assert signal.agent == "sequence"
    assert signal.provisional is False
    assert signal.direction == "neutral"
    assert signal.identity.startswith("seq:")
    assert signal.evidence["summary"] == "doji"


async def test_sequence_rule_does_not_fire_without_the_shape():
    signal, blocked = await RuleEngine.evaluate_rule(
        _sequence_rule(), _doji_bars(20, doji_last=False), dry_run=True
    )
    assert signal is None
    assert blocked == BLOCKED_NO_MATCH


async def test_sequence_identity_is_the_matched_bar_times(monkeypatch):
    """Two sweeps over the same closed bar must agree, or dedup cannot work."""
    async def no_exists(_key):
        return False

    monkeypatch.setattr(RuleEventRepository, "exists", no_exists)
    bars = _doji_bars(20)
    a, _ = await RuleEngine.evaluate_rule(_sequence_rule(), bars, dry_run=True)
    b, _ = await RuleEngine.evaluate_rule(_sequence_rule(), bars, dry_run=True)
    assert a.identity == b.identity == f"seq:{bars[-1]['time']}"
    assert a.dedup_key() == b.dedup_key()


async def test_sequence_ending_on_a_directional_shape_takes_its_bias(monkeypatch):
    """A bullish engulfing bar reads bullish; a lone doji stays neutral."""
    async def no_exists(_key):
        return False

    monkeypatch.setattr(RuleEventRepository, "exists", no_exists)
    bars = _doji_bars(30, doji_last=False)
    # Previous bar down, last bar up and covering it; bodies well above 0.1 ATR.
    bars[-2].update({"open": 130.0, "close": 124.0, "high": 131.0, "low": 123.0})
    bars[-1].update({"open": 123.5, "close": 131.0, "high": 132.0, "low": 123.0})
    rule = _sequence_rule()
    rule["params"]["steps"] = [{"type": "candle", "shape": "bullish_engulfing"}]

    signal, blocked = await RuleEngine.evaluate_rule(rule, bars, dry_run=True)
    assert blocked is None and signal is not None
    assert signal.direction == "bullish"
    assert signal.evidence["summary"] == "bullish_engulfing"


async def test_sequence_with_a_structure_step_fires_on_a_sweep(monkeypatch):
    """A liquidity sweep of support on the newest closed bar, as a rule."""
    from test_structure import bar, with_support

    async def no_exists(_key):
        return False

    monkeypatch.setattr(RuleEventRepository, "exists", no_exists)
    bars = with_support()
    bars.append(bar(103, 106, 97.5, 104, t=bars[-1]["time"] + 60_000))
    rule = _sequence_rule()
    rule["params"]["steps"] = [{"type": "structure", "event": "sweep", "side": "bullish"}]

    signal, blocked = await RuleEngine.evaluate_rule(rule, bars, dry_run=True)
    assert blocked is None and signal is not None
    assert signal.direction == "bullish"
    assert signal.evidence["summary"] == "bullish sweep"
