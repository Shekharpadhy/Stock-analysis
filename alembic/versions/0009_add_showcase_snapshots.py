"""add showcase_snapshots table

Pre-computed full-fidelity analysis snapshots for a curated demo ticker list.
On cloud-IP deployments yfinance + FMP free tier together can't fill every
field for non-US listings; the showcase pipeline runs from a residential IP
(developer's laptop or scheduled GitHub Action), persists the complete
result here, and the analyze endpoint serves it when live fetch returns
sparse data.

Revision ID: 0009_add_showcase_snapshots
Revises: 0008_release_fix
Create Date: 2026-06-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0009_add_showcase_snapshots'
down_revision = '0008_release_fix'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'showcase_snapshots',
        sa.Column('ticker',        sa.String(),  nullable=False),
        sa.Column('raw_json',      sa.Text(),    nullable=False),
        sa.Column('advanced_json', sa.Text(),    nullable=False),
        sa.Column('quality_json',  sa.Text(),    nullable=False),
        sa.Column('refreshed_at',  sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('ticker'),
    )


def downgrade() -> None:
    op.drop_table('showcase_snapshots')
