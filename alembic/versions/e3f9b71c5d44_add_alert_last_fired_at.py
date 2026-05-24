"""add last_fired_at to alert_subscriptions

Revision ID: e3f9b71c5d44
Revises: d7e2a4c81f93
Create Date: 2026-05-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'e3f9b71c5d44'
down_revision = 'd7e2a4c81f93'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('alert_subscriptions') as batch_op:
        batch_op.add_column(sa.Column('last_fired_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('alert_subscriptions') as batch_op:
        batch_op.drop_column('last_fired_at')
