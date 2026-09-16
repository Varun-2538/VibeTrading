"""
From a candidate tape to fires, through the live engine's own decision.

Each bar's close is the clock: persistence counts closes and cooldown measures
from the close of the bar that fired. Filters are applied here, which is why
one tape serves every filter value a tuning run tries.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from services.rule_decision import Candidate, FiringState, decide, first_passing


@dataclass(frozen=True)
class TapeSignal:
    index: int
    time: int
    identity: str
    direction: str
    provisional: bool


def _candidates(row: list) -> List[Candidate]:
    return [
        Candidate(identity=c[0], direction=c[1], provisional=c[2], evidence={}, confidence=c[3], strength=c[4])
        for c in row[1]
    ]


def signals_from_tape(
    tape: List[list],
    candles: List[Dict[str, Any]],
    params: Dict[str, Any],
    *,
    timeframe_ms: int,
    persist_bars: int,
    cooldown_secs: int,
    start: int,
    end: int,
) -> List[TapeSignal]:
    by_index = {int(r[0]): r for r in tape}
    state = FiringState()
    out: List[TapeSignal] = []

    for i in range(start, end):
        tape_row = by_index.get(i)
        chosen = first_passing(params["agent"], params, _candidates(tape_row)) if tape_row else None
        opened = datetime.fromtimestamp(int(candles[i]["time"]) / 1000, tz=timezone.utc)
        closed = opened + timedelta(milliseconds=timeframe_ms)

        decision = decide(
            state,
            chosen.identity if chosen else None,
            opened,
            persist_bars=persist_bars,
            cooldown_secs=cooldown_secs,
            now=closed,
        )
        state = decision.state
        if chosen is not None and decision.blocked is None:
            out.append(TapeSignal(i, int(candles[i]["time"]), chosen.identity, chosen.direction, chosen.provisional))
            state = replace(state, last_fired_at=closed)

    return out


def distinct_setups(signals: List[TapeSignal]) -> List[TapeSignal]:
    """
    The first fire of each setup. A live rule re-fires on every bar its setup
    persists; those fires are one observation, and counting them as many would
    make a confidence interval look far tighter than the evidence allows.
    """
    seen = set()
    out = []
    for s in signals:
        if s.identity not in seen:
            seen.add(s.identity)
            out.append(s)
    return out
