"""link alert_subscriptions to users via user_id

Revision ID: f4a8e632b9d1
Revises: e3f9b71c5d44
Create Date: 2026-05-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a8e632b9d1'
down_revision = 'e3f9b71c5d44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add user_id (nullable — existing rows are admin-owned globals)
    with op.batch_alter_table('alert_subscriptions') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.drop_constraint(
            'uq_alert_ticker_condition_email', type_='unique',
        )
        batch_op.create_unique_constraint(
            'uq_alert_user_ticker_condition_email',
            ['user_id', 'ticker', 'condition', 'email'],
        )
        batch_op.create_index(
            'ix_alert_subscriptions_user_id', ['user_id'], unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('alert_subscriptions') as batch_op:
        batch_op.drop_index('ix_alert_subscriptions_user_id')
        batch_op.drop_constraint(
            'uq_alert_user_ticker_condition_email', type_='unique',
        )
        batch_op.create_unique_constraint(
            'uq_alert_ticker_condition_email',
            ['ticker', 'condition', 'email'],
        )
        batch_op.drop_column('user_id')
