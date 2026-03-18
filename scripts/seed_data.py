"""Seed the database with sample sector and company data."""
import asyncio, json, sys
sys.path.insert(0, ".")

async def seed() -> None:
    print("Seeding database with sample data...")
    # Load fixture data and insert via ORM
    with open("data/fixtures/sample_companies.json") as f:
        companies = json.load(f)
    print(f"Would seed {len(companies)} companies")
    print("Done.")

if __name__ == "__main__":
    asyncio.run(seed())
