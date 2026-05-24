"""add alert_subscriptions table

Revision ID: a1f3c9e72b5d
Revises: 5be4d2830bd1
Create Date: 2026-05-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'a1f3c9e72b5d'
down_revision = '5be4d2830bd1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'alert_subscriptions',
        sa.Column('id',            sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column('ticker',        sa.String(),   nullable=False),
        sa.Column('condition',     sa.String(),   nullable=False),
        sa.Column('threshold',     sa.Float(),    nullable=True),
        sa.Column('email',         sa.String(),   nullable=True),
        sa.Column('slack_webhook', sa.String(),   nullable=True),
        sa.Column('active',        sa.Boolean(),  nullable=False, server_default='1'),
        sa.Column('created_at',    sa.DateTime(), nullable=True),
        sa.Column('updated_at',    sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticker', 'condition', 'email',
                            name='uq_alert_ticker_condition_email'),
    )
    op.create_index('ix_alert_subscriptions_ticker', 'alert_subscriptions',
                    ['ticker'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_alert_subscriptions_ticker', table_name='alert_subscriptions')
    op.drop_table('alert_subscriptions')
