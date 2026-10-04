"""
The idempotency key, which is all that stands between a crashed process and a
double spend.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.execution.keys import LEG_FOR_KIND, REASON_FOR_KIND, client_order_id
from services.trade_plan import PARITY_VERSION

INTENT = "11111111-1111-1111-1111-111111111111"


def test_the_same_intent_and_leg_always_give_the_same_key():
    """
    Regenerated after a crash, in another process, on another day: identical. That
    is the whole property - a key with a clock or a counter in it would let a
    retry look like a new order.
    """
    assert client_order_id(INTENT, "entry") == client_order_id(INTENT, "entry")
    assert len(client_order_id(INTENT, "entry")) == 32


def test_each_leg_and_each_intent_is_its_own_key():
    keys = {client_order_id(INTENT, leg) for leg in ("entry", "stop", "target", "exit", "flatten")}
    assert len(keys) == 5
    other = "22222222-2222-2222-2222-222222222222"
    assert client_order_id(other, "entry") != client_order_id(INTENT, "entry")


def test_an_unknown_leg_is_refused_rather_than_hashed():
    with pytest.raises(ValueError):
        client_order_id(INTENT, "sideways")


def test_the_parity_version_is_part_of_the_key():
    """
    Changing how a stop is placed makes a different order, so it must not be able
    to collide with one written under the old arithmetic.
    """
    import hashlib

    expected = hashlib.sha256(f"{PARITY_VERSION}|{INTENT}|entry".encode()).hexdigest()[:32]
    assert client_order_id(INTENT, "entry") == expected


def test_every_intent_kind_maps_to_a_leg_and_a_reason():
    kinds = ("entry", "exit_stop", "exit_target", "exit_time", "exit_opposite", "flatten")
    assert set(LEG_FOR_KIND) == set(kinds)
    # Every kind but the entry asks the venue to close, and says why.
    assert set(REASON_FOR_KIND) == set(kinds) - {"entry"}
    assert REASON_FOR_KIND["exit_stop"] == "stop"
