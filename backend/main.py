import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.config import settings
from backend.logging_config import configure_logging
from backend.database.db import init_db
from backend.api.routes import router
from backend.api.ws import router as ws_router
from backend.limiter import limiter
from backend.services.price_stream import price_broadcast_loop
from backend.services.ml_model import load_model_from_disk
from backend.services.scheduler import start_scheduler, shutdown_scheduler

# Install the formatter before anyone else logs (modules imported above
# may have already grabbed the root logger; configure_logging() resets it).
configure_logging(level=settings.log_level, fmt=settings.log_format)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 0. Refuse to start in production with insecure defaults — this is a
    #    safety gate that runs BEFORE any DB / external connection.
    settings.validate_for_production()

    # 1. Bring the schema up to date (Alembic) before serving traffic.
    init_db()

    # 2. Load persisted ML model (non-fatal if not present yet).
    load_model_from_disk()

    # 3. Start the background price-broadcast loop.
    broadcast_task = asyncio.create_task(price_broadcast_loop())
    log.info("price_stream: broadcast loop started")

    # 4. Start the APScheduler-driven periodic jobs (alerts, retraining…).
    start_scheduler()

    yield

    # 5. Graceful shutdown — stop scheduler then cancel the broadcast task.
    shutdown_scheduler()

    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
    log.info("price_stream: broadcast loop stopped")


app = FastAPI(
    title="Banking Client Sector Intelligence",
    description="Real-time sector intelligence dashboard for banking clients — "
                "risk signals, peer benchmarking, and SEC filing analysis.",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Rate limiting (per-IP, slowapi) ──────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── CORS — explicit allowlist instead of "*" ─────────────────────────────────
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router,    prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(os.path.join(frontend_path, "index.html"))
