"""WebSocket endpoint for real-time price streaming to dashboard.

Subscribes to Redis Pub/Sub channel 'realtime:all' and broadcasts
to all connected WebSocket clients.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket):
        self._connections.remove(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, data: str):
        """Send data to all connected clients."""
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket endpoint for real-time price updates.

    Clients connect and receive all real-time tick data.
    Optional: send {"subscribe": ["005930", "000660"]} to filter stocks.
    """
    await manager.connect(ws)
    subscribed_codes: set[str] | None = None  # None = all stocks

    try:
        while True:
            # Listen for client messages (subscription filters)
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=60)
                msg = json.loads(data)
                if "subscribe" in msg:
                    subscribed_codes = set(msg["subscribe"])
                    await ws.send_text(json.dumps({"type": "subscribed", "stocks": list(subscribed_codes)}))
                elif msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send keepalive
                await ws.send_text(json.dumps({"type": "heartbeat"}))
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


async def redis_to_websocket_bridge(redis_client):
    """Background task: subscribe to Redis and broadcast to WebSocket clients.

    Runs as asyncio task during app lifespan.
    """
    while True:
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("realtime:all")
            logger.info("Redis→WebSocket bridge started (channel: realtime:all)")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    if manager.count > 0:
                        await manager.broadcast(data)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Redis→WebSocket bridge error: %s, reconnecting...", e)
            await asyncio.sleep(3)
