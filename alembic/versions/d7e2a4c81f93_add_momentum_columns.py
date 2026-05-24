"""add momentum columns to companies

Revision ID: d7e2a4c81f93
Revises: c8d4b1f05e2a
Create Date: 2026-05-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7e2a4c81f93'
down_revision = 'c8d4b1f05e2a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('companies') as batch_op:
        batch_op.add_column(sa.Column('momentum_score',      sa.Float(),  nullable=True))
        batch_op.add_column(sa.Column('momentum_label',      sa.String(), nullable=True))
        batch_op.add_column(sa.Column('momentum_components', sa.Text(),   nullable=True))
        batch_op.add_column(sa.Column('momentum_raw',        sa.Text(),   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('companies') as batch_op:
        batch_op.drop_column('momentum_raw')
        batch_op.drop_column('momentum_components')
        batch_op.drop_column('momentum_label')
        batch_op.drop_column('momentum_score')
