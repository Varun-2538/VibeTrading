"""
The pure half of the rule engine: what matched, and whether it fires.

RuleEngine reads candles and writes rule state to the database; what it decides
lives here, with no I/O and no clock of its own. That is what lets a backtest
replay history through exactly the decisions the live engine makes - the
replay passes each bar's close as "now", the sweep passes the wall clock.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from analysis.candles import SHAPE_BIAS
from analysis.patterns_big import PATTERN_BIAS
from analysis.sequence import describe_steps, match_sequence
from models.rule_schemas import STRENGTH_ORDER

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


# --- candidates --------------------------------------------------------------
#
# Every matcher is "list what could match, then take the first that passes the
# filter". Split that way, a backtest can record the candidates once and try
# many filter values without re-running the detectors, and the live engine
# still gets exactly the answer the single-pass matcher gave.


@dataclass(frozen=True)
class Candidate:
    identity: str
    direction: str
    provisional: bool
    evidence: Dict[str, Any]
    confidence: Optional[float] = None
    strength: Optional[str] = None


def candle_time(candle: Dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(candle["time"]) / 1000, tz=timezone.utc)


def strong_enough(strength: Optional[str], minimum: str) -> bool:
    try:
        return STRENGTH_ORDER.index(strength) >= STRENGTH_ORDER.index(minimum)
    except ValueError:
        return False


def pattern_identity(pattern: Dict[str, Any]) -> str:
    """
    Identity from the pattern's pivot times.

    Point keys differ by kind (low1/peak/low2 versus high1/trough/high2), so
    read the times out of the values and sort rather than naming the keys.
    """
    times = sorted(int(p["time"]) for p in pattern["points"].values())
    stamp = ":".join(str(t) for t in times)
    return f"{pattern['kind']}:{stamp}:{pattern['state']}"


def pattern_candidates(params: Dict[str, Any], patterns: Sequence[Dict[str, Any]]) -> List[Candidate]:
    kinds = set(params.get("kinds") or ())
    states = set(params.get("states") or ())
    # The detector already orders most actionable first; keep that order.
    return [
        Candidate(
            identity=pattern_identity(p),
            direction=PATTERN_BIAS.get(p["kind"], "neutral"),
            provisional=p["state"] != "confirmed",
            evidence=p,
            confidence=float(p["confidence"]),
        )
        for p in patterns
        if p["kind"] in kinds and p["state"] in states
    ]


def liquidity_candidates(
    params: Dict[str, Any],
    levels: Dict[str, Any],
    closes: Sequence[float],
) -> List[Candidate]:
    side = params.get("side", "support")
    event = params.get("event", "approach")
    proximity = float(params.get("proximity_pct", 0.3))

    if event == "approach":
        key = "support_levels" if side == "support" else "resistance_levels"
        # Approaching support is a potential bounce; resistance a rejection.
        direction = "bullish" if side == "support" else "bearish"
        return [
            Candidate(
                identity=f"{side}:approach:{level['price']:.8g}",
                direction=direction,
                provisional=False,
                evidence=level,
                strength=level["strength"],
            )
            for level in levels.get(key, [])
            if level["distance_pct"] <= proximity
        ]

    if len(closes) < 2:
        return []
    previous, last = closes[-2], closes[-1]

    # A break has to be searched across both lists: detect_levels classifies a
    # level against the latest close, so the moment price closes through a
    # support it is reported as resistance. The crossing decides, not the label.
    out: List[Candidate] = []
    for level in list(levels.get("support_levels", [])) + list(levels.get("resistance_levels", [])):
        price = float(level["price"])
        if side == "support" and previous > price >= last:
            out.append(Candidate(f"support:break:{price:.8g}", "bearish", False, level, strength=level["strength"]))
        elif side == "resistance" and previous < price <= last:
            out.append(Candidate(f"resistance:break:{price:.8g}", "bullish", False, level, strength=level["strength"]))
    return out


# Steps that say which way they point. Everything else is read from the bar.
CROSSING_STEPS = ("indicator", "ema_cross", "macd_cross", "stoch_cross", "bollinger", "vwap_cross")


def step_direction(step: Dict[str, Any], candle: Dict[str, Any]) -> str:
    """
    Which way a sequence points, judged by its final step.

    A crossing knows its own direction. A squeeze, a volume spike or a range
    expansion does not - they say "something is happening", not which way - so
    they take the colour of the bar they fired on.
    """
    kind = step.get("type", "candle")
    if kind in CROSSING_STEPS:
        return "bullish" if step.get("cross", "above") == "above" else "bearish"
    if kind == "structure":
        return step.get("side", "neutral")
    if kind == "candle":
        return SHAPE_BIAS.get(step.get("shape", ""), "neutral")

    close, opened = float(candle["close"]), float(candle["open"])
    if close > opened:
        return "bullish"
    if close < opened:
        return "bearish"
    return "neutral"


def sequence_candidates(params: Dict[str, Any], candles: Sequence[Dict[str, Any]]) -> List[Candidate]:
    """
    Identity is the bar time of every matched step. Direction comes from the
    final step: a cross above reads bullish, below bearish, a structure step
    its side, a lone candle its shape's bias. Never provisional.
    """
    steps = params.get("steps") or []
    picked = match_sequence(candles, steps, int(params.get("within_bars", 3)))
    if picked is None:
        return []

    times = [int(candles[i]["time"]) for i in picked]
    direction = step_direction(steps[-1], candles[picked[-1]])

    evidence = {
        "summary": describe_steps(steps),
        "steps": [
            {**step, "bar_time": candle_time(candles[i]).isoformat()}
            for step, i in zip(steps, picked)
        ],
    }
    return [Candidate("seq:" + ":".join(str(t) for t in times), direction, False, evidence)]


def first_passing(agent: str, params: Dict[str, Any], candidates: Sequence[Candidate]) -> Optional[Candidate]:
    if agent == "pattern":
        floor = float(params.get("min_confidence", 0))
        return next((c for c in candidates if (c.confidence or 0) >= floor), None)
    if agent == "liquidity":
        minimum = params.get("min_strength", "medium")
        return next((c for c in candidates if strong_enough(c.strength, minimum)), None)
    return candidates[0] if candidates else None


def as_match(candidate: Optional[Candidate]) -> Optional[Tuple[str, str, bool, Dict[str, Any]]]:
    if candidate is None:
        return None
    return candidate.identity, candidate.direction, candidate.provisional, candidate.evidence
