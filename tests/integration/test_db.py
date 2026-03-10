import pytest
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
async def test_db_session(db: AsyncSession):
    result = await db.execute(__import__("sqlalchemy").text("SELECT 1"))
    assert result.scalar() == 1
