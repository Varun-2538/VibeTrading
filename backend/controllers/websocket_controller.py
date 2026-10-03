from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List, Optional
import asyncio
import json
from datetime import datetime
from services.auth_service import AuthError, read_token
from services.market_data_service import MarketDataService

router = APIRouter(tags=["WebSocket"])

# How long a /ws/rules socket may stay silent before it must have authenticated.
AUTH_GRACE_SECONDS = 10


class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.

    Two separate registries, because the two kinds of traffic have different
    audiences. Market data is public and fans out by symbol. A fired strategy
    signal belongs to exactly one owner and fans out by owner_key - it must never
    travel on a symbol channel, which is how it previously reached every visitor
    watching that pair.
    """

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.owner_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, symbol: str):
        """Accept and register a new WebSocket connection"""
        await websocket.accept()
        if symbol not in self.active_connections:
            self.active_connections[symbol] = []
        self.active_connections[symbol].append(websocket)

    def disconnect(self, websocket: WebSocket, symbol: str):
        """Remove a WebSocket connection"""
        if symbol in self.active_connections:
            if websocket in self.active_connections[symbol]:
                self.active_connections[symbol].remove(websocket)
            if len(self.active_connections[symbol]) == 0:
                del self.active_connections[symbol]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to specific WebSocket"""
        await websocket.send_json(message)

    async def broadcast_to_symbol(self, message: dict, symbol: str):
        """
        Broadcast message to all connections for a symbol.

        Public market data only. Anything belonging to one user goes through
        send_to_owner instead.
        """
        if symbol in self.active_connections:
            disconnected = []
            for connection in self.active_connections[symbol]:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.append(connection)

            # Clean up disconnected clients
            for connection in disconnected:
                self.disconnect(connection, symbol)

    def register_owner(self, websocket: WebSocket, owner_key: str):
        """
        Register an already-accepted socket against its signed-in owner.

        The socket is accepted before this, because it has to be accepted to send
        the token that says who it belongs to.
        """
        self.owner_connections.setdefault(owner_key, []).append(websocket)

    def disconnect_owner(self, websocket: WebSocket, owner_key: str):
        """Remove an owner's socket, dropping the key once it is empty."""
        sockets = self.owner_connections.get(owner_key)
        if not sockets:
            return
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            del self.owner_connections[owner_key]

    async def send_to_owner(self, message: dict, owner_key: str):
        """
        Deliver to every socket belonging to one owner, and no one else.

        Best effort by design: an owner with no socket open right now simply does
        not get the push. The event row is already committed, and the panel
        refetches its feed on mount and on reconnect, so nothing is lost.
        """
        sockets = self.owner_connections.get(owner_key)
        if not sockets:
            return

        disconnected = []
        for connection in list(sockets):
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect_owner(connection, owner_key)


# Global connection manager
manager = ConnectionManager()


# Route order matters here. Starlette matches in the order routes are declared,
# so "/ws/rules" MUST be declared before "/ws/{symbol}" - otherwise the path
# parameter swallows it and a client asking for the rules channel silently gets
# the market stream for a symbol named "rules". Do not reorder these.

async def _authenticate(websocket: WebSocket) -> Optional[str]:
    """
    Read the opening auth frame and return the owner it names.

    The token arrives in a message rather than a query string on purpose: query
    strings are written to access logs, and a browser cannot set headers on a
    WebSocket. Returns None when the socket should be closed - the caller does the
    closing, since only it knows whether the peer is still there.
    """
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=AUTH_GRACE_SECONDS
        )
    except (asyncio.TimeoutError, WebSocketDisconnect):
        return None
    except Exception:
        return None

    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(message, dict) or message.get("type") != "auth":
        return None

    token = message.get("token")
    if not isinstance(token, str) or not token:
        return None

    try:
        return read_token(token)
    except AuthError:
        return None


@router.websocket("/ws/rules")
async def rules_websocket(websocket: WebSocket):
    """
    A signed-in owner's fired strategy signals.

    Replaces /ws/strategy/{symbol}, which accepted its socket without ever
    registering it with the manager and so could not receive a broadcast at all.
    Being keyed by owner rather than symbol also means a rule on one pair reaches
    the user while they are looking at another - one socket for the session
    instead of one per chart.

    The first frame must be {"type": "auth", "token": "<jwt>"}.
    """
    await websocket.accept()

    owner_key = await _authenticate(websocket)
    if owner_key is None:
        try:
            # 1008 is policy violation: the socket was well-formed, the caller
            # just never proved who it was.
            await websocket.close(code=1008, reason="Authentication required")
        except RuntimeError:
            # Already gone - it disconnected rather than authenticating.
            pass
        return

    manager.register_owner(websocket, owner_key)

    try:
        await websocket.send_json({
            "type": "authenticated",
            "address": owner_key,
            "timestamp": datetime.utcnow().isoformat()
        })

        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                # A malformed frame is not worth tearing the socket down for.
                continue

    except Exception as e:
        print(f"Rules WebSocket error: {e}")
    finally:
        manager.disconnect_owner(websocket, owner_key)


@router.websocket("/ws/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    """
    WebSocket endpoint for real-time market data updates

    Provides:
    - Real-time price updates (every hour for 1h timeframe)
    - Technical indicator updates
    - Strategy signals

    Args:
        symbol: Trading pair to subscribe to
    """
    await manager.connect(websocket, symbol)

    try:
        # Send initial connection message
        await manager.send_personal_message({
            "type": "connection",
            "message": f"Connected to {symbol} stream",
            "timestamp": datetime.utcnow().isoformat()
        }, websocket)

        # Send initial market data
        try:
            market_summary = await MarketDataService.get_market_summary(symbol, "1h")
            await manager.send_personal_message({
                "type": "market_summary",
                "data": market_summary,
                "timestamp": datetime.utcnow().isoformat()
            }, websocket)
        except Exception as e:
            await manager.send_personal_message({
                "type": "error",
                "message": f"Failed to fetch initial data: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }, websocket)

        # Listen for messages and send periodic updates
        while True:
            try:
                # Wait for client messages or timeout for updates
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=3600.0  # 1 hour timeout (matches 1h candle update)
                )

                # Handle client messages
                message = json.loads(data)
                message_type = message.get("type")

                if message_type == "ping":
                    await manager.send_personal_message({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

                elif message_type == "request_update":
                    # Send current market data
                    market_summary = await MarketDataService.get_market_summary(
                        symbol, message.get("timeframe", "1h")
                    )
                    await manager.send_personal_message({
                        "type": "market_update",
                        "data": market_summary,
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

            except asyncio.TimeoutError:
                # Send periodic update (every hour)
                try:
                    market_summary = await MarketDataService.get_market_summary(symbol, "1h")
                    await manager.send_personal_message({
                        "type": "periodic_update",
                        "data": market_summary,
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)
                except Exception as e:
                    await manager.send_personal_message({
                        "type": "error",
                        "message": f"Update failed: {str(e)}",
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

            except WebSocketDisconnect:
                manager.disconnect(websocket, symbol)
                break

            except Exception as e:
                await manager.send_personal_message({
                    "type": "error",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }, websocket)

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        manager.disconnect(websocket, symbol)


async def broadcast_price_update(symbol: str, price_data: dict):
    """
    Broadcast price update to all connected clients for a symbol

    Args:
        symbol: Trading pair
        price_data: Price update data
    """
    await manager.broadcast_to_symbol({
        "type": "price_update",
        "data": price_data,
        "timestamp": datetime.utcnow().isoformat()
    }, symbol)


async def broadcast_strategy_signal(owner_key: str, signal_data: dict):
    """
    Send a fired signal to the owner of the rule that fired it.

    This used to take a symbol and call broadcast_to_symbol, which delivered one
    user's fired rule to every browser watching that pair. The audience is now the
    owner, and strategy signals no longer travel on the symbol channel at all - so
    the leak cannot come back by someone forgetting a filter.

    Args:
        owner_key: Lowercased wallet address that owns the rule
        signal_data: Signal data
    """
    await manager.send_to_owner({
        "type": "strategy_signal",
        "data": signal_data,
        "timestamp": datetime.utcnow().isoformat()
    }, owner_key)
