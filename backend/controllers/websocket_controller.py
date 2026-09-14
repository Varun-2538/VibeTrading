from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List
import asyncio
import json
from datetime import datetime
from services.market_data_service import MarketDataService

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

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
        """Broadcast message to all connections for a symbol"""
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


# Global connection manager
manager = ConnectionManager()


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


@router.websocket("/ws/strategy/{symbol}")
async def strategy_websocket(websocket: WebSocket, symbol: str):
    """
    WebSocket endpoint for real-time strategy updates

    Provides:
    - Strategy execution status
    - Entry/exit signals
    - Risk alerts

    Args:
        symbol: Trading pair
    """
    await websocket.accept()

    try:
        await websocket.send_json({
            "type": "connection",
            "message": f"Connected to strategy stream for {symbol}",
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

                # Add strategy-specific logic here

            except WebSocketDisconnect:
                break
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                })

    except Exception as e:
        print(f"Strategy WebSocket error: {e}")
    finally:
        await websocket.close()


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


async def broadcast_strategy_signal(symbol: str, signal_data: dict):
    """
    Broadcast strategy signal to all connected clients

    Args:
        symbol: Trading pair
        signal_data: Signal data
    """
    await manager.broadcast_to_symbol({
        "type": "strategy_signal",
        "data": signal_data,
        "timestamp": datetime.utcnow().isoformat()
    }, symbol)
