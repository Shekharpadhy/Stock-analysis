"""add scheduler_lock table

Revision ID: i7d2e9f04a58
Revises: h6c1d8e93f47
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'i7d2e9f04a58'
down_revision = 'h6c1d8e93f47'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'scheduler_lock',
        sa.Column('name',        sa.String(),   nullable=False),
        sa.Column('worker_id',   sa.String(),   nullable=False),
        sa.Column('acquired_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at',  sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('name'),
    )


def downgrade() -> None:
    op.drop_table('scheduler_lock')
