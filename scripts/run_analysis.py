"""Run composite risk analysis for a ticker or sector from the CLI."""
import argparse
import asyncio
import sys

sys.path.insert(0, ".")


async def run(ticker: str, sector: str | None) -> None:
    from backend.database.db import get_db
    from backend.services.ensemble_risk import EnsembleRiskService

    async for db in get_db():
        svc = EnsembleRiskService(db)
        result = await svc.compute_risk_score(ticker, sector)
        print(f"\nRisk score for {ticker}: {result}")
        break


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sector risk analysis")
    parser.add_argument("ticker", help="Stock ticker symbol (e.g. HDFC, ICICI)")
    parser.add_argument("--sector", default=None, help="Override GICS sector")
    args = parser.parse_args()
    asyncio.run(run(args.ticker, args.sector))


if __name__ == "__main__":
    main()
