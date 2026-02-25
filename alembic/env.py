"""Alembic environment — wired to the project's config and ORM metadata.

The database URL comes from backend.config.settings (the same .env the app
uses) and the target metadata is backend.database.db.Base — so autogenerate
diffs against the live CompanyRecord model.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the project root importable so `backend.*` resolves when Alembic runs.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.config import settings              # noqa: E402
from backend.database.db import Base             # noqa: E402
import backend.database.db                       # noqa: E402,F401  (registers models)

config = context.config

# NOTE: disable_existing_loggers=False is required — init_db() runs this env
# at app startup, and the default (True) would wipe uvicorn's and the app's
# own loggers, silencing all logging after the first migration.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Override the .ini URL with the app's configured database URL.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Metadata used by --autogenerate to detect schema changes.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI needed)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,        # SQLite-safe ALTER TABLE
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,    # SQLite-safe ALTER TABLE
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
