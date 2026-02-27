"""add audit log table"""
revision = "c4d5e6f7"; down_revision = None; branch_labels = None; depends_on = None
from alembic import op; import sqlalchemy as sa

def upgrade() -> None:
    op.create_table("add_audit_log_table",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer),
    sa.Column("action", sa.String(200)),
    sa.Column("resource", sa.String(100)),

        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table("add_audit_log_table")
