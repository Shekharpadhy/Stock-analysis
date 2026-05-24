"""add audit_log table

Revision ID: g5b9a4c1e8d2
Revises: f4a8e632b9d1
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'g5b9a4c1e8d2'
down_revision = 'f4a8e632b9d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id',        sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column('actor',     sa.String(),   nullable=False),
        sa.Column('action',    sa.String(),   nullable=False),
        sa.Column('target',    sa.String(),   nullable=True),
        sa.Column('extra',     sa.Text(),     nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_log_actor',     'audit_log', ['actor'])
    op.create_index('ix_audit_log_action',    'audit_log', ['action'])
    op.create_index('ix_audit_log_target',    'audit_log', ['target'])
    op.create_index('ix_audit_log_timestamp', 'audit_log', ['timestamp'])


def downgrade() -> None:
    op.drop_index('ix_audit_log_timestamp', table_name='audit_log')
    op.drop_index('ix_audit_log_target',    table_name='audit_log')
    op.drop_index('ix_audit_log_action',    table_name='audit_log')
    op.drop_index('ix_audit_log_actor',     table_name='audit_log')
    op.drop_table('audit_log')
