"""add api keys table"""
revision = "a6f7a8b9"; down_revision = None; branch_labels = None; depends_on = None
from alembic import op; import sqlalchemy as sa

def upgrade() -> None:
    op.create_table("add_api_keys_table",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key_hash", sa.String(200)),
    sa.Column("name", sa.String(100)),
    sa.Column("is_active", sa.Boolean, default=True),

        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table("add_api_keys_table")
