"""Performance benchmarks for core scoring services."""
import asyncio
import time
from collections.abc import Coroutine
from typing import Any


async def bench(label: str, coro: Coroutine[Any, Any, Any], n: int = 50) -> None:
    t0 = time.perf_counter()
    for _ in range(n):
        await coro
    elapsed = time.perf_counter() - t0
    print(f"  {label:40s} {elapsed:.3f}s total  {elapsed/n*1000:.2f} ms/call  ({n} runs)")


async def main() -> None:
    print("Banking Sector Intelligence — Performance Benchmarks")
    print("=" * 60)
    print("(Add coroutine calls to bench() to measure services)")
    # Example:
    # from backend.services.ensemble_risk import EnsembleRiskService
    # await bench("EnsembleRisk.compute_risk_score", svc.compute_risk_score("HDFCBANK"))


if __name__ == "__main__":
    asyncio.run(main())
