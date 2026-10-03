"""The engine's decisions with no database and no clock of their own."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.rule_decision import (
    BLOCKED_COOLDOWN,
    BLOCKED_NO_MATCH,
    BLOCKED_PERSISTENCE,
    FiringState,
    decide,
    pending_dict,
    state_from_rule,
)

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def run(state, identity, bar, persist=0, cooldown=0, now=None):
    return decide(state, identity, bar, persist_bars=persist, cooldown_secs=cooldown, now=now or bar + HOUR)


def test_no_match_clears_the_streak_and_records_the_bar():
    d = run(FiringState(pending_identity="a", pending_seen=2, last_bar_time=T), None, T + HOUR)
    assert d.blocked == BLOCKED_NO_MATCH
    assert d.state.pending_identity is None and d.state.last_bar_time == T + HOUR


def test_without_persistence_a_match_fires_at_once():
    d = run(FiringState(), "a", T)
    assert d.blocked is None
    assert (d.state.pending_identity, d.state.pending_seen) == ("a", 1)


def test_persistence_needs_the_setup_to_survive_a_close():
    first = run(FiringState(), "a", T, persist=1)
    assert first.blocked == BLOCKED_PERSISTENCE
    second = run(first.state, "a", T + HOUR, persist=1)
    assert second.blocked is None and second.state.pending_seen == 2


def test_re_evaluating_the_same_bar_does_not_advance_the_streak():
    first = run(FiringState(), "a", T, persist=1)
    again = run(first.state, "a", T, persist=1)
    assert again.blocked == BLOCKED_PERSISTENCE and again.state.pending_seen == 1


def test_a_different_setup_restarts_the_streak():
    first = run(FiringState(), "a", T, persist=1)
    other = run(first.state, "b", T + HOUR, persist=1)
    assert other.blocked == BLOCKED_PERSISTENCE and other.state.pending_seen == 1


def test_cooldown_is_measured_against_the_clock_it_is_given():
    fired = FiringState(last_fired_at=T)
    assert run(fired, "a", T, cooldown=7200, now=T + HOUR).blocked == BLOCKED_COOLDOWN
    assert run(fired, "a", T, cooldown=7200, now=T + 2 * HOUR).blocked is None


def test_decide_never_records_a_fire_itself():
    d = run(FiringState(), "a", T)
    assert d.state.last_fired_at is None


def test_rule_state_round_trip():
    rule = {"pending": {"identity": "x", "seen": 3}, "last_candle_time": T, "last_fired_at": None}
    state = state_from_rule(rule)
    assert state == FiringState("x", 3, T, None)
    assert pending_dict(state) == {"identity": "x", "seen": 3}
    assert pending_dict(FiringState()) is None
    assert state_from_rule({"pending": None, "last_candle_time": None, "last_fired_at": None}) == FiringState()


from services.rule_decision import (
    Candidate,
    first_passing,
    liquidity_candidates,
    pattern_candidates,
    sequence_candidates,
)


def pat(kind="W", state="confirmed", confidence=80.0, t0=1000):
    keys = ("low1", "peak", "low2") if kind == "W" else ("high1", "trough", "high2")
    return {
        "kind": kind, "state": state, "confidence": confidence,
        "points": {k: {"time": t0 + i, "price": 100.0} for i, k in enumerate(keys)},
        "neckline": 105.0, "target": 110.0,
    }


def test_pattern_candidates_ignore_confidence_and_keep_detector_order():
    params = {"kinds": ["W"], "states": ["confirmed"], "min_confidence": 70}
    cands = pattern_candidates(params, [pat(confidence=50, t0=1), pat(kind="M"), pat(confidence=90, t0=2)])
    assert [c.confidence for c in cands] == [50.0, 90.0]
    chosen = first_passing("pattern", params, cands)
    assert chosen.confidence == 90.0 and chosen.direction == "bullish"


def test_liquidity_approach_candidates_keep_weak_levels_but_not_far_ones():
    levels = {"support_levels": [
        {"price": 99.9, "strength": "weak", "test_count": 2, "distance_pct": 0.1},
        {"price": 99.0, "strength": "strong", "test_count": 9, "distance_pct": 0.25},
        {"price": 90.0, "strength": "strong", "test_count": 9, "distance_pct": 10.0},
    ], "resistance_levels": []}
    params = {"side": "support", "event": "approach", "proximity_pct": 0.3, "min_strength": "medium"}
    cands = liquidity_candidates(params, levels, [100.0, 100.0])
    assert [c.strength for c in cands] == ["weak", "strong"]
    assert first_passing("liquidity", params, cands).identity == "support:approach:99"
    assert first_passing("liquidity", {**params, "min_strength": "weak"}, cands).identity == "support:approach:99.9"


def test_sequence_candidates_are_the_single_match_or_nothing():
    flat = [{"time": i * 60_000, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}
            for i in range(30)]
    params = {"steps": [{"type": "candle", "shape": "hammer"}], "within_bars": 3}
    assert sequence_candidates(params, flat) == []
    assert first_passing("sequence", params, []) is None


def test_first_passing_returns_the_first_sequence_candidate():
    c = Candidate("seq:1", "neutral", False, {})
    assert first_passing("sequence", {}, [c]) is c
