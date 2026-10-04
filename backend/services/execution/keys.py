"""
The idempotency key for one venue write.

Derived only from durable facts - never a clock, never an attempt counter - so a
retry after any failure regenerates it byte for byte. The row that carries it is
inserted *before* the venue is called, and the same string is handed to the venue,
so a duplicate is refused on both sides of the wire.

The parity version is in the hash on purpose: changing how a stop is placed makes
a genuinely different order, and it should not be able to collide with one written
under the old arithmetic.
"""
import hashlib

from services.trade_plan import PARITY_VERSION

# The legs a single intent can produce. 'entry' opens; the rest close.
LEGS = ("entry", "stop", "target", "exit", "flatten", "cancel")


def client_order_id(intent_id: str, leg: str) -> str:
    if leg not in LEGS:
        raise ValueError(f"unknown leg {leg!r}")
    raw = f"{PARITY_VERSION}|{intent_id}|{leg}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# Which leg an intent kind writes. A close is one write whatever triggered it, and
# the leg records which condition it was, so an audit reads without a join.
LEG_FOR_KIND = {
    "entry": "entry",
    "exit_stop": "stop",
    "exit_target": "target",
    "exit_time": "exit",
    "exit_opposite": "exit",
    "flatten": "flatten",
}

# And which close reason the venue is asked for.
REASON_FOR_KIND = {
    "exit_stop": "stop",
    "exit_target": "target",
    "exit_time": "time",
    "exit_opposite": "opposite",
    "flatten": "flatten",
}
