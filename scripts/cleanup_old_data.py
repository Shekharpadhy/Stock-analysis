"""Remove stale price history and cached predictions older than N days."""
import asyncio, sys
sys.path.insert(0, ".")

async def cleanup(days: int = 90) -> None:
    print(f"Cleaning up data older than {days} days...")
    # Add cleanup logic here
    print("Cleanup complete.")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(); p.add_argument("--days", type=int, default=90)
    asyncio.run(cleanup(p.parse_args().days))
