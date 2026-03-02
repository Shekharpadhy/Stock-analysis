"""add watchlists table"""
revision = "96a7b8c9"; down_revision = None; branch_labels = None; depends_on = None
from alembic import op; import sqlalchemy as sa

def upgrade() -> None:
    op.create_table("add_watchlists_table",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer),
    sa.Column("tickers", sa.JSON),
    sa.Column("name", sa.String(100)),

        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table("add_watchlists_table")
