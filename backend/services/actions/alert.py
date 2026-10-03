from typing import Any, Dict

from services.actions.base import ActionResult


class AlertAction:
    """
    Pushes the fire to any browser watching the symbol.

    Delivery is best effort. The event row is already committed before this
    runs, and the panel refetches its feed on mount and on reconnect, so a
    dropped broadcast costs a toast and never a lost signal.
    """

    async def execute(self, rule: Dict[str, Any], signal: Any, event_id: int) -> ActionResult:
        # Imported here, not at module scope: websocket_controller imports the
        # market data service, so a top-level import risks a cycle.
        from controllers.websocket_controller import broadcast_strategy_signal

        payload = {
            "event_id": event_id,
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "agent": signal.agent,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "direction": signal.direction,
            "price": signal.price,
            "candle_time": signal.candle_time.isoformat(),
            "provisional": signal.provisional,
            "evidence": signal.evidence,
        }

        try:
            await broadcast_strategy_signal(signal.symbol, payload)
        except Exception as exc:  # noqa: BLE001 - see docstring
            return ActionResult(status="failed", result={"error": str(exc)})

        return ActionResult(status="sent", result={"channel": "ws"})
