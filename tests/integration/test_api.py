import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health(async_client: AsyncClient):
    resp = await async_client.get("/health")
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_sectors_requires_auth(async_client: AsyncClient):
    resp = await async_client.get("/sectors")
    assert resp.status_code in (401, 403)
