import time, functools, logging
logger = logging.getLogger(__name__)

def timed(fn):
    @functools.wraps(fn)
    async def wrapper(*a, **kw):
        t0 = time.perf_counter()
        result = await fn(*a, **kw)
        logger.debug("%s took %.3fs", fn.__name__, time.perf_counter() - t0)
        return result
    return wrapper

def retry(max_attempts: int = 3, delay: float = 0.5):
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*a, **kw):
            for attempt in range(max_attempts):
                try:
                    return await fn(*a, **kw)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    await __import__("asyncio").sleep(delay * (2 ** attempt))
        return wrapper
    return decorator
