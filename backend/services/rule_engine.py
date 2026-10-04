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

from analysis.levels import detect_levels
from analysis.patterns_big import detect_all_patterns
from repositories.rule_repository import RuleEventRepository, RuleRepository
from services.actions import ACTIONS
from services.actions.base import PENDING
from services.candle_service import CandleService, CandleFetchError, UnknownTimeframe

from services.rule_decision import (  # noqa: F401  (BLOCKED_* are re-exported)
    BLOCKED_COOLDOWN,
    BLOCKED_DEDUP,
    BLOCKED_NO_MATCH,
    BLOCKED_PERSISTENCE,
    as_match,
    candle_time,
    decide,
    first_passing,
    liquidity_candidates,
    pattern_candidates,
    pattern_identity,
    pending_dict,
    sequence_candidates,
    state_from_rule,
    strong_enough,
)


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


# Kept under their old names: callers and tests import these.
_candle_time = candle_time
_strong_enough = strong_enough
_pattern_identity = pattern_identity


def _match_pattern(params, patterns):
    return as_match(first_passing("pattern", params, pattern_candidates(params, patterns)))


def _match_liquidity(params, levels, closes):
    return as_match(first_passing("liquidity", params, liquidity_candidates(params, levels, closes)))


def _match_sequence(params, candles):
    return as_match(first_passing("sequence", params, sequence_candidates(params, candles)))


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
                patterns = detect_all_patterns(
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

        identity = matched[0] if matched is not None else None
        decision = decide(
            state_from_rule(rule),
            identity,
            candle_time,
            persist_bars=int(rule["persist_bars"] or 0),
            cooldown_secs=int(rule["cooldown_secs"] or 0),
            now=datetime.now(timezone.utc),
        )
        if not dry_run:
            # Also clears a half-built streak when the setup is gone.
            await RuleRepository.set_pending(rule["id"], pending_dict(decision.state), candle_time)

        if matched is None:
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

        if decision.blocked is not None:
            return signal, decision.blocked

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
            await RuleEventRepository.set_action_result_if(
                event["id"], PENDING, "skipped", {"reason": f"no handler for '{action_kind}'"}
            )
            return event

        # A provisional signal can still repaint, so it may only ever alert.
        if signal.provisional and action_kind != "alert":
            await RuleEventRepository.set_action_result_if(
                event["id"], PENDING, "skipped", {"reason": "provisional signal"}
            )
            return event

        result = await action.execute(rule, signal, event["id"])
        # Only from 'pending': an action that handed the fire to another process
        # may already have had its status moved on by that process.
        await RuleEventRepository.set_action_result_if(
            event["id"], PENDING, result.status, result.result
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
                        pattern_cache[key] = detect_all_patterns(
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
