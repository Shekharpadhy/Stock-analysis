"""
WebSocket endpoints for real-time price streaming.

Endpoint
────────
  GET /ws/prices   (upgraded to WebSocket)

Authentication: none required — this stream carries only public market-price
data.  Clients should reconnect with exponential back-off on disconnect.

See backend/services/price_stream.py for the full protocol documentation.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.price_stream import manager, send_snapshot

router = APIRouter()
log = logging.getLogger(__name__)


@router.websocket("/ws/prices")
async def ws_prices(ws: WebSocket) -> None:
    """
    Subscribe to live price ticks for all tracked tickers.

    Server → Client messages (JSON):
      {"type": "price_snapshot", "data": [...], "timestamp": "...", "note": "..."}
      {"type": "price_update",   "data": [...], "timestamp": "...", "note": "..."}
      {"type": "heartbeat",      "timestamp": "..."}

    data item: {"ticker": "AAPL", "price": 185.50, "change_pct": +1.26}
    change_pct is relative to the price stored at last analysis time.

    Client → Server: messages are silently discarded (read-only stream).
    """
    await manager.connect(ws)
    try:
        # Send stored prices immediately so the UI isn't blank on load.
        await send_snapshot(ws)

        # Keep the connection alive; the broadcast loop pushes live updates.
        # Any messages sent by the client are consumed and discarded.
        async for _ in ws.iter_text():
            pass

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws:prices  unexpected error — %s", exc)
    finally:
        manager.disconnect(ws)
