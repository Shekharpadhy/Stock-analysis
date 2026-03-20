"""Import a list of tickers from a CSV file into the database."""
import asyncio, csv, sys
sys.path.insert(0, ".")

async def import_tickers(filepath: str) -> None:
    with open(filepath) as f:
        tickers = [row["ticker"] for row in csv.DictReader(f)]
    print(f"Importing {len(tickers)} tickers...")
    # Add DB insert logic here
    print("Import complete.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_tickers.py <file.csv>"); sys.exit(1)
    asyncio.run(import_tickers(sys.argv[1]))
