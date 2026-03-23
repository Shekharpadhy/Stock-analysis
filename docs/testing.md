# Testing Guide

## Running Tests

```bash
make test                         # all tests with coverage
pytest tests/unit/ -v             # unit tests only
pytest tests/integration/ -v      # integration tests only
pytest tests/ -k "test_risk" -v   # filter by name
```

## Test Structure

```
tests/
├── conftest.py          # shared fixtures (db, redis, client)
├── test_auth.py         # auth unit tests
├── test_*.py            # per-module unit tests
└── integration/
    ├── test_api.py      # end-to-end API tests
    └── test_db.py       # database integration tests
```

## Writing Tests

Use the async fixtures from `conftest.py`:
```python
@pytest.mark.asyncio
async def test_example(db, async_client):
    resp = await async_client.get("/health")
    assert resp.status_code == 200
```
