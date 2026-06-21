"""add pending_snapshots table

Queue of tickers users searched that didn't have a showcase snapshot.  The
nightly refresh job (GitHub Action) drains the queue, so any ticker a user
searches today gets a full snapshot by tomorrow.

Revision ID: 0010_add_pending_snapshots
Revises: 0009_add_showcase_snapshots
Create Date: 2026-06-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0010_add_pending_snapshots'
down_revision = '0009_add_showcase_snapshots'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'pending_snapshots',
        sa.Column('ticker',             sa.String(),  nullable=False),
        sa.Column('first_requested_at', sa.DateTime(), nullable=False),
        sa.Column('last_requested_at',  sa.DateTime(), nullable=False),
        sa.Column('request_count',      sa.Integer(),  nullable=False,
                  server_default='1'),
        sa.PrimaryKeyConstraint('ticker'),
    )


def downgrade() -> None:
    op.drop_table('pending_snapshots')
