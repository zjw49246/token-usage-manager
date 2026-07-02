"""P22：模型别名表

Revision ID: 008
Revises: 007
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("alias", sa.String(150), nullable=False),
        sa.Column("target_model_id", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_aliases_alias", "model_aliases", ["alias"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_model_aliases_alias", table_name="model_aliases")
    op.drop_table("model_aliases")
