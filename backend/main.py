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
from backend.database.db import init_db
from backend.api.routes import router
from backend.limiter import limiter


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Bring the schema up to date (Alembic) before serving traffic.
    init_db()
    yield


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

app.include_router(router, prefix="/api/v1")

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(os.path.join(frontend_path, "index.html"))
