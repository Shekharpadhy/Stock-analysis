"""Validate ingested financial data for completeness and consistency."""
import asyncio
import sys

sys.path.insert(0, ".")


async def validate() -> bool:
    from backend.database.db import get_db
    from backend.services.quality import DataQualityService

    errors: list[str] = []
    async for db in get_db():
        svc = DataQualityService(db)
        result = await svc.run_all_checks()
        errors.extend(result.get("errors", []))
        break

    if errors:
        print(f"Validation failed — {len(errors)} issue(s) found:")
        for err in errors:
            print(f"  ✗ {err}")
        return False

    print("All data quality checks passed.")
    return True


if __name__ == "__main__":
    ok = asyncio.run(validate())
    sys.exit(0 if ok else 1)
