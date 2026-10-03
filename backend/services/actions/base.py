from dataclasses import dataclass, field
from typing import Any, Dict, Protocol, runtime_checkable


@dataclass
class ActionResult:
    # One of: sent, skipped, failed. Stored on the event row so a fire that was
    # recorded but not delivered is distinguishable from one that never fired.
    status: str
    result: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Action(Protocol):
    """
    Something to do when a rule fires.

    Implementations must not raise: a failure to deliver is recorded on the
    event, because the fire itself is already a durable fact by this point.
    """

    async def execute(self, rule: Dict[str, Any], signal: Any, event_id: int) -> ActionResult:
        ...
