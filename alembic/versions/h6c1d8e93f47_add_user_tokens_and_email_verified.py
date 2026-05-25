"""add user_tokens table + email_verified flag

Revision ID: h6c1d8e93f47
Revises: g5b9a4c1e8d2
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'h6c1d8e93f47'
down_revision = 'g5b9a4c1e8d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. email_verified flag on users
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column(
            'email_verified', sa.Boolean(),
            nullable=False, server_default='0',
        ))

    # 2. user_tokens
    op.create_table(
        'user_tokens',
        sa.Column('id',         sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column('user_id',    sa.Integer(),  nullable=False),
        sa.Column('purpose',    sa.String(),   nullable=False),
        sa.Column('token_hash', sa.String(),   nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at',    sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash', name='uq_user_tokens_hash'),
    )
    op.create_index('ix_user_tokens_user_id', 'user_tokens', ['user_id'])
    op.create_index('ix_user_tokens_purpose', 'user_tokens', ['purpose'])
    op.create_index('ix_user_tokens_hash',    'user_tokens', ['token_hash'])


def downgrade() -> None:
    op.drop_index('ix_user_tokens_hash',    table_name='user_tokens')
    op.drop_index('ix_user_tokens_purpose', table_name='user_tokens')
    op.drop_index('ix_user_tokens_user_id', table_name='user_tokens')
    op.drop_table('user_tokens')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('email_verified')
