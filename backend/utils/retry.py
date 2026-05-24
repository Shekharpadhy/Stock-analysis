import asyncio

async def with_retry(coro_fn, max_attempts: int = 3, base_delay: float = 0.5):
    """Execute an async callable with exponential backoff retry."""
    for attempt in range(max_attempts):
        try:
            return await coro_fn()
        except Exception:
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(base_delay * (2 ** attempt))
