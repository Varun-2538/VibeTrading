"""
The pure half of the rule engine: what matched, and whether it fires.

RuleEngine reads candles and writes rule state to the database; what it decides
lives here, with no I/O and no clock of its own. That is what lets a backtest
replay history through exactly the decisions the live engine makes - the
replay passes each bar's close as "now", the sweep passes the wall clock.
"""
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Dict, Optional

# Reasons a matching signal still did not fire. Surfaced by the test endpoint so
# a user can tell "my rule is wrong" from "my rule already fired".
BLOCKED_NO_MATCH = "no_match"
BLOCKED_PERSISTENCE = "persistence"
BLOCKED_COOLDOWN = "cooldown"
BLOCKED_DEDUP = "dedup"


@dataclass(frozen=True)
class FiringState:
    """What the engine remembers about a rule between bars."""

    pending_identity: Optional[str] = None
    pending_seen: int = 0
    last_bar_time: Optional[datetime] = None
    last_fired_at: Optional[datetime] = None


@dataclass(frozen=True)
class Decision:
    state: FiringState
    blocked: Optional[str]


def state_from_rule(rule: Dict[str, Any]) -> FiringState:
    pending = rule.get("pending") or {}
    return FiringState(
        pending_identity=pending.get("identity"),
        pending_seen=int(pending.get("seen", 1)) if pending else 0,
        last_bar_time=rule.get("last_candle_time"),
        last_fired_at=rule.get("last_fired_at"),
    )


def pending_dict(state: FiringState) -> Optional[Dict[str, Any]]:
    if state.pending_identity is None:
        return None
    return {"identity": state.pending_identity, "seen": state.pending_seen}


def decide(
    state: FiringState,
    identity: Optional[str],
    bar_time: datetime,
    *,
    persist_bars: int,
    cooldown_secs: int,
    now: datetime,
) -> Decision:
    """
    Whether a setup seen on `bar_time` fires, and the state to carry forward.

    Persistence counts consecutive closed bars showing the same setup; a
    re-evaluation of a bar already counted does not inflate the streak.
    Cooldown is measured from the last fire to `now`. Recording a fire is the
    caller's job, because only the caller knows whether the fire happened.
    """
    if identity is None:
        return Decision(
            replace(state, pending_identity=None, pending_seen=0, last_bar_time=bar_time),
            BLOCKED_NO_MATCH,
        )

    seen = 1
    if persist_bars:
        same_setup = state.pending_identity == identity
        advanced = state.last_bar_time is None or state.last_bar_time < bar_time
        if same_setup and advanced:
            seen = state.pending_seen + 1
        elif same_setup:
            seen = state.pending_seen

    carried = replace(state, pending_identity=identity, pending_seen=seen, last_bar_time=bar_time)

    if persist_bars and seen <= persist_bars:
        return Decision(carried, BLOCKED_PERSISTENCE)

    if cooldown_secs and state.last_fired_at is not None:
        if (now - state.last_fired_at).total_seconds() < cooldown_secs:
            return Decision(carried, BLOCKED_COOLDOWN)

    return Decision(carried, None)
