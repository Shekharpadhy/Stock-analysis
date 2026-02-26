"""add risk scores table"""
revision = "e2b3c4d5"; down_revision = None; branch_labels = None; depends_on = None
from alembic import op; import sqlalchemy as sa

def upgrade() -> None:
    op.create_table("add_risk_scores_table",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(20)),
    sa.Column("score", sa.Float),
    sa.Column("model_version", sa.String(50)),

        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table("add_risk_scores_table")
