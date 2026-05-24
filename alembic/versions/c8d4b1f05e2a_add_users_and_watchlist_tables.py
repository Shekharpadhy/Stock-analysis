"""add users and watchlist tables

Revision ID: c8d4b1f05e2a
Revises: a1f3c9e72b5d
Create Date: 2026-05-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'c8d4b1f05e2a'
down_revision = 'a1f3c9e72b5d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id',              sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column('username',        sa.String(),   nullable=False),
        sa.Column('email',           sa.String(),   nullable=False),
        sa.Column('hashed_password', sa.String(),   nullable=False),
        sa.Column('role',            sa.String(),   nullable=False, server_default='user'),
        sa.Column('is_active',       sa.Boolean(),  nullable=False, server_default='1'),
        sa.Column('created_at',      sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username', name='uq_users_username'),
        sa.UniqueConstraint('email',    name='uq_users_email'),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_email',    'users', ['email'],    unique=True)

    # ── watchlist ──────────────────────────────────────────────────────────────
    op.create_table(
        'watchlist',
        sa.Column('id',       sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column('user_id',  sa.Integer(),  nullable=False),
        sa.Column('ticker',   sa.String(),   nullable=False),
        sa.Column('notes',    sa.Text(),     nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'ticker', name='uq_watchlist_user_ticker'),
    )
    op.create_index('ix_watchlist_user_id', 'watchlist', ['user_id'], unique=False)
    op.create_index('ix_watchlist_ticker',  'watchlist', ['ticker'],  unique=False)


def downgrade() -> None:
    op.drop_index('ix_watchlist_ticker',  table_name='watchlist')
    op.drop_index('ix_watchlist_user_id', table_name='watchlist')
    op.drop_table('watchlist')

    op.drop_index('ix_users_email',    table_name='users')
    op.drop_index('ix_users_username', table_name='users')
    op.drop_table('users')
