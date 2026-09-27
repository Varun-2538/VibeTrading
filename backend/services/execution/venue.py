"""
What the executor is allowed to assume about the thing it trades on.

The interface is deliberately narrower than a venue usually gets, because a vault
is narrower: it opens one position with its stop, its target and its deadline in
the same transaction, and it closes that position. There is no separate "place the
trigger orders" step, which means **the window between an open position and a
protected one does not exist**. That window is the most dangerous state an
executor can be in, and this design removes it rather than defending it.

The two error types are the most important part of this file. `VenueRejected` is a
promise about state - it definitely did not happen, so a retry is safe.
`VenueUnknown` is an admission - we do not know, so nothing may be retried until
reconciliation has asked the venue what is true. An adapter that cannot tell the
two apart must raise the second one.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Protocol, runtime_checkable


class VenueError(Exception):
    """A venue call failed."""


class VenueRejected(VenueError):
    """
    The venue refused and definitely did not execute: a revert, a cap, a bad
    argument. Safe to retry. Raising this is a claim about state, not a
    description of a message.
    """


class VenueUnknown(VenueError):
    """
    We do not know whether it executed - a timeout, a dropped connection, a node
    that answered with nothing useful. Never retried directly; the intent waits
    for reconciliation to ask the venue what happened.
    """


@dataclass(frozen=True)
class Quote:
    """The venue's current price for the asset, in stable units."""

    price: float
    at: datetime


@dataclass(frozen=True)
class Fill:
    venue_fill_id: str
    price: float
    qty: float
    fee_usd: float
    gas_usd: float
    at: datetime
    tx_ref: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class VenuePosition:
    """
    What the venue says is open, which is the only authority on the subject.

    Our own row is a record of what we believe; when the two disagree,
    reconciliation believes this one and halts rather than guessing.
    """

    open: bool
    qty: float = 0.0
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: Optional[float] = None
    deadline: Optional[datetime] = None


# The reasons a position may be closed. The first three are conditions the venue
# itself verifies, so anyone may push them; the last two are ours to ask for.
CLOSE_REASONS = ("stop", "target", "time", "opposite", "flatten")


@runtime_checkable
class Venue(Protocol):
    """
    One vault, one market. Implementations must raise VenueRejected or
    VenueUnknown and nothing else, because the executor's retry policy is built
    entirely on that distinction.
    """

    async def quote(self) -> Quote:
        ...

    async def balance(self) -> float:
        """Stable available to trade with, in dollars."""
        ...

    async def position(self) -> VenuePosition:
        ...

    async def open(
        self,
        *,
        notional_usd: float,
        stop_price: float,
        target_price: Optional[float],
        deadline: datetime,
        min_out: Optional[float],
        client_order_id: str,
    ) -> Fill:
        """
        Buy the asset, and write where this position gets out.

        The stop, the target and the deadline are part of this call because the
        vault stores them here and never lets them change afterwards.
        """
        ...

    async def close(self, *, reason: str, client_order_id: str) -> Fill:
        ...
