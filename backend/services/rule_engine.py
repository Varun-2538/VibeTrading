"""
Evaluates strategy rules against closed candles and fires their actions.

Three things protect against acting on a signal that later disappears:

1. Only closed bars are ever evaluated. The caller slices off the in-progress
   candle, because the pattern detector judges state against the newest close.
2. `confirmed` is the only state that fires without being marked provisional.
3. A signal must survive `persist_bars` further closes before it counts.

On top of that, a per-signal dedup key makes firing idempotent, so a repeated
or overlapping sweep cannot raise the same alert twice.
"""
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from analysis.candles import SHAPE_BIAS
from analysis.levels import detect_levels
from analysis.patterns import detect_double_patterns
from analysis.sequence import describe_steps, match_sequence
from models.rule_schemas import STRENGTH_ORDER
from repositories.rule_repository import RuleEventRepository, RuleRepository
from services.actions import ACTIONS
from services.candle_service import CandleService, CandleFetchError, UnknownTimeframe

# Reasons a matching signal still did not fire. Surfaced by the test endpoint so
# a user can tell "my rule is wrong" from "my rule already fired".
BLOCKED_NO_MATCH = "no_match"
BLOCKED_PERSISTENCE = "persistence"
BLOCKED_COOLDOWN = "cooldown"
BLOCKED_DEDUP = "dedup"


@dataclass
class Signal:
    """
    A rule's condition, met on a specific closed bar.

    Actions consume this rather than raw detector output, so the detectors can
    be retuned without changing what an executor sees.
    """

    rule_id: str
    agent: str
    symbol: str
    timeframe: str
    candle_time: datetime
    # Stable across sweeps for the same underlying setup - this is what makes
    # persistence and dedup meaningful.
    identity: str
    direction: str
    price: float
    provisional: bool
    evidence: Dict[str, Any] = field(default_factory=dict)

    def dedup_key(self) -> str:
        raw = f"{self.rule_id}|{self.identity}|{int(self.candle_time.timestamp() * 1000)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candle_time": self.candle_time.isoformat(),
            "identity": self.identity,
            "direction": self.direction,
            "price": self.price,
            "provisional": self.provisional,
            "evidence": self.evidence,
        }


def _candle_time(candle: Dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(candle["time"]) / 1000, tz=timezone.utc)


def _strong_enough(strength: str, minimum: str) -> bool:
    try:
        return STRENGTH_ORDER.index(strength) >= STRENGTH_ORDER.index(minimum)
    except ValueError:
        return False


def _pattern_identity(pattern: Dict[str, Any]) -> str:
    """
    Identity from the pattern's three pivot times.

    Point keys differ by kind (low1/peak/low2 versus high1/trough/high2), so
    read the times out of the values and sort rather than naming the keys.
    """
    times = sorted(int(p["time"]) for p in pattern["points"].values())
    stamp = ":".join(str(t) for t in times)
    return f"{pattern['kind']}:{stamp}:{pattern['state']}"


def _match_pattern(
    params: Dict[str, Any],
    patterns: Sequence[Dict[str, Any]],
) -> Optional[Tuple[str, str, bool, Dict[str, Any]]]:
    kinds = set(params.get("kinds") or ())
    states = set(params.get("states") or ())
    min_confidence = float(params.get("min_confidence", 0))

    # detect_double_patterns already orders most actionable first, so the first
    # acceptable match is the one to report.
    for pattern in patterns:
        if pattern["kind"] not in kinds:
            continue
        if pattern["state"] not in states:
            continue
        if pattern["confidence"] < min_confidence:
            continue

        direction = "bullish" if pattern["kind"] == "W" else "bearish"
        provisional = pattern["state"] != "confirmed"
        return _pattern_identity(pattern), direction, provisional, pattern

    return None


def _match_liquidity(
    params: Dict[str, Any],
    levels: Dict[str, Any],
    closes: Sequence[float],
) -> Optional[Tuple[str, str, bool, Dict[str, Any]]]:
    side = params.get("side", "support")
    minimum = params.get("min_strength", "medium")
    event = params.get("event", "approach")
    proximity = float(params.get("proximity_pct", 0.3))

    if event == "approach":
        key = "support_levels" if side == "support" else "resistance_levels"
        for level in levels.get(key, []):
            if not _strong_enough(level["strength"], minimum):
                continue
            if level["distance_pct"] > proximity:
                continue
            # Approaching support is a potential bounce; approaching resistance
            # is a potential rejection.
            direction = "bullish" if side == "support" else "bearish"
            return (
                f"{side}:approach:{level['price']:.8g}",
                direction,
                False,
                level,
            )
        return None

    if len(closes) < 2:
        return None

    previous, last = closes[-2], closes[-1]

    # A break has to be searched across both lists. detect_levels classifies a
    # level as support or resistance by comparing it to the latest close, so the
    # moment price closes through a support that level is reported as
    # resistance. Which side broke is decided by the crossing, not the label.
    candidates = list(levels.get("support_levels", [])) + list(
        levels.get("resistance_levels", [])
    )

    for level in candidates:
        if not _strong_enough(level["strength"], minimum):
            continue
        price = float(level["price"])

        if side == "support" and previous > price >= last:
            return f"support:break:{price:.8g}", "bearish", False, level
        if side == "resistance" and previous < price <= last:
            return f"resistance:break:{price:.8g}", "bullish", False, level

    return None


def _match_sequence(
    params: Dict[str, Any],
    candles: Sequence[Dict[str, Any]],
) -> Optional[Tuple[str, str, bool, Dict[str, Any]]]:
    """
    Identity is the bar time of every matched step, so the same doji-then-cross
    seen by two sweeps is one signal. Direction comes from the final step: a
    cross above reads bullish, below bearish, and a lone candle shape is
    neutral. Never provisional - every step is settled at candle close.
    """
    steps = params.get("steps") or []
    picked = match_sequence(candles, steps, int(params.get("within_bars", 3)))
    if picked is None:
        return None

    times = [int(candles[i]["time"]) for i in picked]
    identity = "seq:" + ":".join(str(t) for t in times)

    last = steps[-1]
    if last.get("type") == "indicator":
        direction = "bullish" if last.get("cross") == "above" else "bearish"
    else:
        direction = SHAPE_BIAS.get(last.get("shape", ""), "neutral")

    evidence = {
        "summary": describe_steps(steps),
        "steps": [
            {**step, "bar_time": _candle_time(candles[i]).isoformat()}
            for step, i in zip(steps, picked)
        ],
    }
    return identity, direction, False, evidence


class RuleEngine:
    """Sweeps armed rules and fires the ones whose conditions hold."""

    @staticmethod
    async def evaluate_rule(
        rule: Dict[str, Any],
        candles: Sequence[Dict[str, Any]],
        *,
        patterns: Optional[Sequence[Dict[str, Any]]] = None,
        levels: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> Tuple[Optional[Signal], Optional[str]]:
        """
        Decide whether `rule` fires on the last candle of `candles`.

        `candles` must already exclude the in-progress bar. Returns the signal
        and, when it will not fire, why not. A dry run touches nothing.
        """
        if len(candles) < 2:
            return None, BLOCKED_NO_MATCH

        params = rule["params"] or {}
        agent = rule["agent"]
        closed = candles[-1]
        candle_time = _candle_time(closed)

        if agent == "pattern":
            if patterns is None:
                patterns = detect_double_patterns(
                    candles,
                    strictness=params.get("strictness", "balanced"),
                    source=params.get("source", "wick"),
                    scale=params.get("scale", "swing"),
                    max_results=None,
                )
            matched = _match_pattern(params, patterns)
        elif agent == "liquidity":
            if levels is None:
                levels = detect_levels(candles)
            matched = _match_liquidity(
                params, levels, [float(c["close"]) for c in candles]
            )
        elif agent == "sequence":
            # Nothing to share across rules here: the masks depend on each
            # rule's own periods and levels, and they are cheap.
            matched = _match_sequence(params, candles)
        else:
            return None, BLOCKED_NO_MATCH

        if matched is None:
            if not dry_run:
                # Drop any half-built persistence streak: the setup is gone.
                await RuleRepository.set_pending(rule["id"], None, candle_time)
            return None, BLOCKED_NO_MATCH

        identity, direction, provisional, evidence = matched
        signal = Signal(
            rule_id=str(rule["id"]),
            agent=agent,
            symbol=rule["symbol"],
            timeframe=rule["timeframe"],
            candle_time=candle_time,
            identity=identity,
            direction=direction,
            price=float(closed["close"]),
            provisional=provisional,
            evidence=evidence,
        )

        # Persistence: count consecutive closed bars showing the same setup.
        persist_bars = int(rule["persist_bars"] or 0)
        seen = 1
        if persist_bars:
            pending = rule.get("pending") or {}
            last_seen = rule.get("last_candle_time")
            same_setup = pending.get("identity") == identity
            advanced = last_seen is None or last_seen < candle_time

            if same_setup and advanced:
                seen = int(pending.get("seen", 1)) + 1
            elif same_setup and not advanced:
                # Re-evaluating a bar already counted; don't inflate the streak.
                seen = int(pending.get("seen", 1))

            if not dry_run:
                await RuleRepository.set_pending(
                    rule["id"],
                    {"identity": identity, "seen": seen},
                    candle_time,
                )

            if seen <= persist_bars:
                return signal, BLOCKED_PERSISTENCE
        elif not dry_run:
            await RuleRepository.set_pending(
                rule["id"], {"identity": identity, "seen": seen}, candle_time
            )

        cooldown = int(rule["cooldown_secs"] or 0)
        last_fired = rule.get("last_fired_at")
        if cooldown and last_fired:
            elapsed = (datetime.now(timezone.utc) - last_fired).total_seconds()
            if elapsed < cooldown:
                return signal, BLOCKED_COOLDOWN

        if dry_run and await RuleEventRepository.exists(signal.dedup_key()):
            return signal, BLOCKED_DEDUP

        return signal, None

    @staticmethod
    async def fire(rule: Dict[str, Any], signal: Signal) -> Optional[Dict[str, Any]]:
        """
        Record the fire and run its action.

        Returns None when this exact signal already fired - the unique dedup key
        is what decides, so two overlapping sweeps cannot double-alert.
        """
        action_kind = (rule.get("action") or {}).get("kind", "alert")

        event = await RuleEventRepository.insert(
            rule_id=rule["id"],
            owner_key=rule["owner_key"],
            dedup_key=signal.dedup_key(),
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            agent=signal.agent,
            direction=signal.direction,
            price=signal.price,
            candle_time=signal.candle_time,
            provisional=signal.provisional,
            evidence=signal.evidence,
            action_kind=action_kind,
        )
        if event is None:
            return None

        await RuleRepository.mark_fired(rule["id"], event["fired_at"])

        action = ACTIONS.get(action_kind)
        if action is None:
            # An unknown action is recorded and skipped rather than raised: the
            # fire is a real fact even if we cannot act on it.
            await RuleEventRepository.set_action_result(
                event["id"], "skipped", {"reason": f"no handler for '{action_kind}'"}
            )
            return event

        # A provisional signal can still repaint, so it may only ever alert.
        if signal.provisional and action_kind != "alert":
            await RuleEventRepository.set_action_result(
                event["id"], "skipped", {"reason": "provisional signal"}
            )
            return event

        result = await action.execute(rule, signal, event["id"])
        await RuleEventRepository.set_action_result(
            event["id"], result.status, result.result
        )
        return event

    @staticmethod
    async def evaluate_due() -> List[Dict[str, Any]]:
        """
        One sweep over every armed rule. Returns the events that fired.

        Rules are grouped so candles and detector runs are shared: the real cost
        is paid once per (symbol, timeframe) per closed bar, not once per rule.
        """
        rules = await RuleRepository.list_armed()
        if not rules:
            return []

        groups: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = {}
        for rule in rules:
            lookback = int((rule["params"] or {}).get("lookback", 500))
            groups.setdefault((rule["symbol"], rule["timeframe"], lookback), []).append(rule)

        fired: List[Dict[str, Any]] = []

        for (symbol, timeframe, lookback), members in groups.items():
            try:
                candles = await CandleService.get_candles(symbol, timeframe, lookback)
            except (UnknownTimeframe, CandleFetchError) as exc:
                print(f"[RULES] {symbol} {timeframe}: {exc}")
                continue

            # Drop the in-progress candle. Everything downstream assumes this.
            closed = candles[:-1]
            if len(closed) < 2:
                continue

            candle_time = _candle_time(closed[-1])

            # Nothing new has closed for any member, so the detectors would only
            # reproduce the previous answer.
            if all(
                rule["last_candle_time"] is not None
                and rule["last_candle_time"] >= candle_time
                for rule in members
            ):
                continue

            pattern_cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
            levels_cache: Optional[Dict[str, Any]] = None

            for rule in members:
                params = rule["params"] or {}
                patterns = None
                levels = None

                if rule["agent"] == "pattern":
                    key = (
                        params.get("strictness", "balanced"),
                        params.get("source", "wick"),
                        params.get("scale", "swing"),
                    )
                    if key not in pattern_cache:
                        pattern_cache[key] = detect_double_patterns(
                            closed,
                            strictness=key[0],
                            source=key[1],
                            scale=key[2],
                            max_results=None,
                        )
                    patterns = pattern_cache[key]
                elif rule["agent"] == "liquidity":
                    if levels_cache is None:
                        levels_cache = detect_levels(closed)
                    levels = levels_cache

                try:
                    signal, blocked = await RuleEngine.evaluate_rule(
                        rule, closed, patterns=patterns, levels=levels
                    )
                except Exception as exc:  # noqa: BLE001
                    # One bad rule must not abort the sweep for everyone else.
                    print(f"[RULES] rule {rule['id']} failed: {exc}")
                    continue

                if signal is None or blocked is not None:
                    continue

                event = await RuleEngine.fire(rule, signal)
                if event is not None:
                    print(
                        f"[RULES] fired {rule['name']} ({rule['agent']}) "
                        f"{signal.symbol} {signal.timeframe} {signal.direction}"
                    )
                    fired.append(event)

        return fired


rule_engine = RuleEngine()
