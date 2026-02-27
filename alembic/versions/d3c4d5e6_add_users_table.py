"""add users table"""
revision = "d3c4d5e6"; down_revision = None; branch_labels = None; depends_on = None
from alembic import op; import sqlalchemy as sa

def upgrade() -> None:
    op.create_table("add_users_table",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(100), unique=True),
    sa.Column("hashed_password", sa.String(200)),
    sa.Column("is_active", sa.Boolean, default=True),

        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table("add_users_table")
