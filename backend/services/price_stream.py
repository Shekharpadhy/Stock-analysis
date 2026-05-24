"""
Real-time price streaming service.

Architecture
────────────
  price_broadcast_loop()          ← background asyncio task, started in lifespan
      │  every POLL_INTERVAL secs
      ├─ reads tracked tickers from DB
      ├─ calls fetch_prices_batch()  (blocking → run in thread pool)
      └─ ConnectionManager.broadcast()  → all active WebSocket clients

  ws_prices() endpoint            ← one coroutine per connected client
      ├─ ConnectionManager.connect()
      ├─ send_snapshot()            → stored prices immediately on join
      ├─ iter_text() keep-alive     → silently discard client messages
      └─ ConnectionManager.disconnect() on exit

Message protocol (server → client, all JSON)
────────────────────────────────────────────
  price_snapshot  sent once on connection: stored prices from last analysis
  price_update    broadcast every POLL_INTERVAL: live yfinance prices
  heartbeat       sent when no clients were connected during a cycle

  Each data item: {"ticker": "AAPL", "price": 185.50, "change_pct": +1.26}
  change_pct is relative to the price stored at last analysis time — it shows
  drift since the model last ran, NOT intraday change.

NOTE: yfinance free-tier data is typically ~15 minutes delayed.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf
from fastapi import WebSocket

log = logging.getLogger(__name__)

POLL_INTERVAL: int = 30   # seconds between live-price fetches


# ── Connection manager ────────────────────────────────────────────────────────

class ConnectionManager:
    """Thread-safe (asyncio-safe) registry of active WebSocket connections."""

    def __init__(self):
        self._active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)
        log.info("ws:prices  connected  (clients=%d)", len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)
        log.info("ws:prices  disconnected (clients=%d)", len(self._active))

    async def broadcast(self, message: dict) -> None:
        """Send JSON to all clients; silently prune dead connections."""
        if not self._active:
            return
        text = json.dumps(message)
        dead: set[WebSocket] = set()
        for ws in list(self._active):
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._active.discard(ws)
        if dead:
            log.debug("ws:prices  pruned %d dead connection(s)", len(dead))

    async def send(self, ws: WebSocket, message: dict) -> None:
        """Send JSON to one client; discard if the connection is dead."""
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            self._active.discard(ws)

    @property
    def count(self) -> int:
        return len(self._active)


# Module-level singleton shared by the WS endpoint and the broadcast loop.
manager = ConnectionManager()


# ── Price fetching ────────────────────────────────────────────────────────────

def fetch_prices_batch(tickers: list[str]) -> dict[str, float]:
    """
    Fetch last-traded prices for a batch of tickers in a single yfinance call.
    Returns {ticker: price}.  Missing / erroring tickers are omitted.

    This is a *blocking* function — call via asyncio.to_thread().
    yfinance data is ~15 min delayed on the free tier.
    """
    if not tickers:
        return {}
    try:
        data = yf.download(
            " ".join(tickers),
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
        if data.empty:
            return {}

        closes = data["Close"]

        if len(tickers) == 1:
            # Single-ticker download: Close is a Series, not a DataFrame.
            series = closes.dropna()
            return {tickers[0]: float(series.iloc[-1])} if not series.empty else {}

        # Multi-ticker: Close is a DataFrame with tickers as columns.
        result: dict[str, float] = {}
        for t in tickers:
            if t not in closes.columns:
                continue
            col = closes[t].dropna()
            if not col.empty:
                result[t] = float(col.iloc[-1])
        return result

    except Exception as exc:
        log.warning("price_stream: batch fetch failed — %s", exc)
        return {}


# ── Snapshot (on connect) ─────────────────────────────────────────────────────

async def send_snapshot(ws: WebSocket) -> None:
    """
    Send stored (last-analysis) prices to a newly connected client so the UI
    is populated immediately rather than waiting POLL_INTERVAL seconds.
    """
    from backend.database.db import SessionLocal, CompanyRecord   # lazy — avoids circular import
    db = SessionLocal()
    try:
        rows = db.query(CompanyRecord.ticker, CompanyRecord.current_price).all()
    finally:
        db.close()

    if not rows:
        return

    await manager.send(ws, {
        "type": "price_snapshot",
        "data": [
            {"ticker": r.ticker, "price": r.current_price, "change_pct": None}
            for r in rows
            if r.current_price is not None
        ],
        "timestamp": _now_iso(),
        "note": "stored prices from last analysis; live stream starts shortly",
    })


# ── Background broadcast loop ─────────────────────────────────────────────────

async def price_broadcast_loop() -> None:
    """
    Infinite background task — polls yfinance every POLL_INTERVAL seconds and
    broadcasts live prices to all connected WebSocket clients.

    Skips the yfinance fetch when no clients are connected (avoids wasting the
    free-tier rate limit).  A heartbeat is still sent on every third cycle so
    the server's keep-alive mechanism works even during quiet periods.
    """
    cycle = 0
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        cycle += 1

        # ── heartbeat every 3 cycles (~90 s) ─────────────────────────────────
        if cycle % 3 == 0 and manager.count > 0:
            await manager.broadcast({"type": "heartbeat", "timestamp": _now_iso()})

        if manager.count == 0:
            continue

        # ── fetch tickers + stored prices from DB ─────────────────────────────
        from backend.database.db import SessionLocal, CompanyRecord  # lazy import
        db = SessionLocal()
        try:
            rows = db.query(
                CompanyRecord.ticker, CompanyRecord.current_price
            ).all()
        finally:
            db.close()

        if not rows:
            continue

        tickers = [r.ticker for r in rows]
        stored  = {r.ticker: r.current_price for r in rows}

        # ── batch price fetch (blocking I/O → thread pool) ────────────────────
        prices = await asyncio.to_thread(fetch_prices_batch, tickers)
        if not prices:
            log.warning("price_stream: no prices returned — skipping broadcast")
            continue

        # ── compute change vs stored price ────────────────────────────────────
        data: list[dict] = []
        for ticker, live in prices.items():
            base = stored.get(ticker)
            change_pct: Optional[float] = (
                round((live - base) / base * 100, 2)
                if base and base > 0
                else None
            )
            data.append({
                "ticker":     ticker,
                "price":      round(live, 2),
                "change_pct": change_pct,
            })

        await manager.broadcast({
            "type":      "price_update",
            "data":      data,
            "timestamp": _now_iso(),
            "note":      "~15 min delayed (yfinance free tier)",
        })
        log.debug("price_stream: broadcast %d tickers to %d client(s)",
                  len(data), manager.count)


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
