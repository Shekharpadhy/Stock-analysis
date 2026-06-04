"""release fix — no-op stub

The original commit (`2ecbff6 fix(release): handle missing migration column
on upgrade`) introduced this file as a one-line `# migration` stub, which
Alembic refuses to load — it crashes the test suite and blocks any
`alembic upgrade head` (including the Render deploy entrypoint).

Rewriting it as a valid no-op preserves the migration chain so the head
still resolves cleanly.  If you intended this migration to alter the
schema, edit `upgrade()` / `downgrade()` below — the chain anchor
(`down_revision = 'i7d2e9f04a58'`) is correct as long as you want this to
land after the scheduler-lock migration.

Revision ID: 0008_release_fix
Revises: i7d2e9f04a58
Create Date: 2026-06-04 00:00:00.000000
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = '0008_release_fix'
down_revision = 'i7d2e9f04a58'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Intentionally empty — placeholder for the v1.1.0-rc1 release fix."""
    pass


def downgrade() -> None:
    """Intentionally empty — symmetric with upgrade()."""
    pass
