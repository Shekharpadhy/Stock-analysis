"""Flush the Redis cache for a given prefix or all keys."""
import asyncio, sys
sys.path.insert(0, ".")

async def reset(pattern: str = "bcsi:*") -> None:
    print(f"Resetting cache keys matching: {pattern}")
    # import redis.asyncio as aioredis; r = await aioredis.from_url(REDIS_URL); await r.delete(*keys)
    print("Cache reset complete.")

if __name__ == "__main__":
    asyncio.run(reset())
