# Pins the pytest rootdir to the project root so `import backend...` resolves.
#
# Also disables side-effectful background services for the entire test suite:
#   • The APScheduler scheduler — we never want real cron jobs firing during
#     tests, and a TestClient lifespan that started one would leak threads.
#
# These env vars are read by pydantic-settings at Settings() construction time,
# so they MUST be set before any backend module imports `settings`.
import os

os.environ.setdefault("SCHEDULER_ENABLED", "false")
