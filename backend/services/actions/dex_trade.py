"""
What happens when an armed rule fires: an intent is queued, and nothing else.

This runs inside the API's 60-second alert sweep, where `rule_engine.fire` awaits it
inline. So it makes no network call and writes no row of its own. One slow RPC here
would delay every other wallet's alerts, and with `coalesce=True` on the sweep a
multi-minute stall does not merely arrive late - the bars that closed during it are
never evaluated by anyone, because `set_pending` has already moved
`last_candle_time` past them and no dedup key is ever minted. A fire lost that way
cannot be recovered.

What it returns is written into the event's `action_result` by `fire()`, which is
already committing that row. The executor picks queued events up on its own clock.
That is also why there is no transaction problem to solve: there is no window in
which a dedup key has been burnt but no work exists.

The three outcomes mirror `backtest/trades.py::simulate` exactly, and the middle one
is the subtle one. A signal against an open position with `exit_on_opposite` closes
it and does **not** reverse, because `simulate` exits at the opposite signal and
counts that signal as skipped_in_position rather than entering it. Getting this
wrong doubles the live trade count against the report.
"""
from datetime import timedelta
from typing import Any, Dict, Optional

from services.actions.base import ActionResult
from services.trade_plan import PARITY_VERSION, signed_direction, tradable


class DexTradeAction:
    """
    Queues a trade for the executor. Never raises, never blocks, never spends.

    Repositories are attributes rather than imports so a test can hand it fakes,
    and so the sweep's two reads are visible in one place.
    """

    def __init__(self, policies=None, positions=None) -> None:
        self._policies = policies
        self._positions = positions

    @property
    def policies(self):
        if self._policies is None:
            from repositories.execution_repository import ExecutionPolicyRepository

            self._policies = ExecutionPolicyRepository
        return self._policies

    @property
    def positions(self):
        if self._positions is None:
            from repositories.execution_repository import ExecutionPositionRepository

            self._positions = ExecutionPositionRepository
        return self._positions

    async def execute(self, rule: Dict[str, Any], signal: Any, event_id: int) -> ActionResult:
        try:
            return await self._plan(rule, signal, event_id)
        except Exception as exc:  # noqa: BLE001 - Action must not raise; see base.py
            return ActionResult(status="failed", result={"error": str(exc)[:300]})

    async def _plan(self, rule: Dict[str, Any], signal: Any, event_id: int) -> ActionResult:
        owner_key = rule["owner_key"]
        policy = await self.policies.get(str(rule["id"]), owner_key)
        if policy is None or not policy["armed"]:
            return ActionResult("skipped", {"reason": "not armed for execution"})
        if policy["parity_version"] != PARITY_VERSION:
            # The arithmetic that measured this rule is not the arithmetic that
            # would trade it. Refused here as well as at arming, because arming
            # happened in the past and the constant may have moved since.
            return ActionResult(
                "skipped",
                {"reason": "armed under different exit arithmetic", "armed": policy["parity_version"]},
            )

        config = dict(policy["policy"] or {})
        plan = dict(policy["exit_plan"] or {})
        mode = config.get("mode")  # not stored on the policy; the account decides
        direction = _direction(signal.direction, config.get("neutral", "skip"))

        open_position = await self.positions.open_for_rule(owner_key, str(rule["id"]), "live")
        shadow_position = await self.positions.open_for_rule(owner_key, str(rule["id"]), "shadow")
        existing = open_position or shadow_position

        if existing is not None:
            if plan.get("exit_on_opposite") and direction is not None and direction != int(existing["direction"]):
                return ActionResult(
                    "queued",
                    _queued(
                        "exit_opposite", signal, rule, policy, plan, config, event_id,
                        position_id=str(existing["id"]), mode=existing["mode"],
                    ),
                )
            # simulate() counts this as skipped_in_position and moves on.
            return ActionResult("skipped", {"reason": "in_position", "position_id": str(existing["id"])})

        if direction is None:
            # A signal with no direction of its own, and a policy that says to skip
            # those. The alert still happened; the trade does not.
            return ActionResult("skipped", {"reason": "no direction to trade"})
        if not tradable(direction, config.get("sides", "long")):
            # A spot pool cannot short. Recorded rather than silently dropped,
            # because someone watching a bearish rule fire and nothing happen
            # deserves to see why.
            return ActionResult("skipped", {"reason": "a pool cannot short this signal"})

        return ActionResult("queued", _queued("entry", signal, rule, policy, plan, config, event_id, mode=mode))


def _direction(signal_direction: str, neutral: str) -> Optional[int]:
    """
    The signal's direction **without** the venue's side filter.

    The same shape as simulate(), and for the same reason: `exit_on_opposite` needs
    to see a bearish signal on a long-only venue, because there it is not a trade but
    it is still a reason to be out. Filtering here would silently hold the position
    through the exact signal the owner asked to exit on.
    """
    return signed_direction(signal_direction, neutral)


def _queued(
    kind: str,
    signal: Any,
    rule: Dict[str, Any],
    policy: Dict[str, Any],
    plan: Dict[str, Any],
    config: Dict[str, Any],
    event_id: int,
    *,
    position_id: Optional[str] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Everything the executor needs, and nothing it would have to ask the network for.

    `reference_open_time` is the bar after the signal's - the bar `simulate` enters
    at. The executor reads that bar's open when it picks this up, which is the live
    analogue of `opens[i + 1]`, and `not_after` is how much later than that open a
    fill is still the same trade rather than a different one.
    """
    from services.history_service import TIMEFRAME_MS

    step_ms = TIMEFRAME_MS.get(signal.timeframe, 3_600_000)
    reference_open = signal.candle_time + timedelta(milliseconds=step_ms)
    delay = int(config.get("max_entry_delay_secs", 120))
    return {
        "state": "queued",
        "kind": kind,
        "event_id": event_id,
        "position_id": position_id,
        "mode": mode,
        "venue": policy["venue"],
        "market": policy["market"],
        "parity_version": policy["parity_version"],
        "plan": plan,
        "config": config,
        "reference": {
            "signal_bar_time": signal.candle_time.isoformat(),
            "reference_open_time": reference_open.isoformat(),
            "signal_price": float(signal.price),
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            # Carried here so the executor never has to re-read the policy: the
            # rule's ceiling is part of the snapshot it was queued under.
            "max_notional_usd": config.get("max_notional_usd"),
            "max_slippage_bps": config.get("max_slippage_bps"),
        },
        "not_after": (reference_open + timedelta(seconds=delay)).isoformat(),
    }
