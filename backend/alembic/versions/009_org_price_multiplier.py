"""P23：organizations 加 price_multiplier（组织价格倍率）

Revision ID: 009
Revises: 008
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("price_multiplier", sa.Float(), server_default="1", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("price_multiplier")
