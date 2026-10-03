"""
Fired signals reach one owner and nobody else.

This is the regression suite for a real leak: broadcast_strategy_signal used to
call broadcast_to_symbol, so every browser watching a pair received every other
user's fired rules. The tests below pin the two properties that fix it - signals
are addressed by owner, and they no longer travel on the symbol channel at all.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers import websocket_controller as ws
from services.auth_service import issue_token

ALICE = "0x1111111111111111111111111111111111111111"
BOB = "0x2222222222222222222222222222222222222222"


class FakeSocket:
    """Records what was sent, and can pretend to be a dead connection."""

    def __init__(self, frames=None, fail: bool = False):
        self.sent = []
        self.frames = list(frames or [])
        self.fail = fail
        self.closed_with = None

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("socket is gone")
        self.sent.append(message)

    async def receive_text(self):
        if not self.frames:
            raise WebSocketDisconnect()
        return self.frames.pop(0)

    async def close(self, code=1000, reason=""):
        self.closed_with = (code, reason)


@pytest.fixture
def manager():
    return ws.ConnectionManager()


async def test_signal_reaches_only_its_owner(manager):
    alice, bob = FakeSocket(), FakeSocket()
    manager.register_owner(alice, ALICE)
    manager.register_owner(bob, BOB)

    await manager.send_to_owner({"type": "strategy_signal"}, ALICE)

    assert len(alice.sent) == 1
    assert bob.sent == []


async def test_every_socket_of_one_owner_is_served(manager):
    """Two tabs, or a phone and a laptop, both signed in as the same wallet."""
    first, second = FakeSocket(), FakeSocket()
    manager.register_owner(first, ALICE)
    manager.register_owner(second, ALICE)

    await manager.send_to_owner({"type": "strategy_signal"}, ALICE)

    assert len(first.sent) == 1
    assert len(second.sent) == 1


async def test_signals_do_not_travel_on_the_symbol_channel(manager, monkeypatch):
    """
    The heart of the leak. A socket subscribed to BTCUSDT market data must not
    receive a strategy signal, however many rules fire on BTCUSDT.
    """
    watcher = FakeSocket()
    manager.active_connections["BTCUSDT"] = [watcher]
    owner = FakeSocket()
    manager.register_owner(owner, ALICE)

    monkeypatch.setattr(ws, "manager", manager)
    await ws.broadcast_strategy_signal(ALICE, {"rule_id": "abc"})

    assert watcher.sent == []
    assert len(owner.sent) == 1
    assert owner.sent[0]["type"] == "strategy_signal"


async def test_an_owner_with_nothing_open_is_not_an_error(manager):
    """Best effort: the event row is already committed and the panel refetches."""
    await manager.send_to_owner({"type": "strategy_signal"}, ALICE)


async def test_dead_sockets_are_dropped(manager):
    dead, alive = FakeSocket(fail=True), FakeSocket()
    manager.register_owner(dead, ALICE)
    manager.register_owner(alive, ALICE)

    await manager.send_to_owner({"type": "strategy_signal"}, ALICE)

    assert manager.owner_connections[ALICE] == [alive]


def test_disconnecting_the_last_socket_drops_the_owner(manager):
    """Otherwise the registry grows a key per wallet that ever connected."""
    socket = FakeSocket()
    manager.register_owner(socket, ALICE)
    manager.disconnect_owner(socket, ALICE)

    assert ALICE not in manager.owner_connections


def test_disconnecting_an_unknown_socket_is_harmless(manager):
    manager.disconnect_owner(FakeSocket(), ALICE)


# --- the opening auth frame ------------------------------------------------


async def test_auth_frame_with_a_valid_token_identifies_the_owner():
    token = issue_token(ALICE)["token"]
    socket = FakeSocket(frames=[json.dumps({"type": "auth", "token": token})])

    assert await ws._authenticate(socket) == ALICE


@pytest.mark.parametrize(
    "frame",
    [
        json.dumps({"type": "auth", "token": "not-a-jwt"}),
        json.dumps({"type": "auth"}),
        json.dumps({"type": "ping"}),
        json.dumps(["auth"]),
        "not json at all",
    ],
    ids=["bad token", "no token", "wrong type", "not an object", "not json"],
)
async def test_unauthenticated_openings_are_refused(frame):
    assert await ws._authenticate(FakeSocket(frames=[frame])) is None


async def test_a_socket_that_says_nothing_is_refused():
    assert await ws._authenticate(FakeSocket(frames=[])) is None


# --- routing ---------------------------------------------------------------


def test_the_rules_route_is_declared_before_the_symbol_route():
    """
    Starlette matches routes in declaration order, so "/ws/{symbol}" declared
    first swallows "/ws/rules" and hands back the market stream for a symbol
    named "rules". It fails silently - the socket opens and even sends frames -
    which is why this is pinned rather than left to review. It shipped once.
    """
    paths = [route.path for route in ws.router.routes]

    assert "/ws/rules" in paths
    assert "/ws/{symbol}" in paths
    assert paths.index("/ws/rules") < paths.index("/ws/{symbol}")
