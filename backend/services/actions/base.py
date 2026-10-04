from dataclasses import dataclass, field
from typing import Any, Dict, Protocol, Tuple, runtime_checkable


# Every status an event's delivery can hold, so the set is greppable rather than
# scattered through string literals. 'queued' is not a delivery: it means the
# fire was handed to another process, which will move the row on itself.
ACTION_STATUSES: Tuple[str, ...] = ("pending", "queued", "sent", "skipped", "failed")

# The only status fire() may move a row away from. Anything else means a second
# writer got there first, and the right response is to stop.
PENDING: Tuple[str, ...] = ("pending",)


@dataclass
class ActionResult:
    # One of ACTION_STATUSES above. Stored on the event row so a fire that was
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
