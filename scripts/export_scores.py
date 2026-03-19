"""Export latest risk scores to CSV."""
import asyncio, csv, sys
sys.path.insert(0, ".")

async def export(output: str = "risk_scores_export.csv") -> None:
    print(f"Exporting risk scores to {output}...")
    # Add DB query and CSV write logic here
    print("Export complete.")

if __name__ == "__main__":
    asyncio.run(export())
