"""
Sanity-check that the synchronous SQLAlchemy engine wired through
backend/database/db.py actually responds to `SELECT 1` and that the schema
exposed by Base.metadata matches what every other test uses.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import (
    Base, CompanyRecord, User, AlertSubscription, AuditLog, UserToken,
)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


def test_select_one(engine):
    Session = sessionmaker(bind=engine)
    with Session() as db:
        assert db.execute(text("SELECT 1")).scalar() == 1


@pytest.mark.parametrize("model", [
    CompanyRecord, User, AlertSubscription, AuditLog, UserToken,
])
def test_model_tables_created(engine, model):
    """create_all() materialises every Base subclass — protects against the
    'I added a new model and forgot to import it' regression."""
    assert model.__tablename__ in Base.metadata.tables
    with engine.connect() as conn:
        # Smoke: a SELECT against the empty table must succeed.
        conn.execute(text(f"SELECT * FROM {model.__tablename__} LIMIT 1"))
