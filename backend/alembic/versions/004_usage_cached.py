"""P7：usage_records 加 cached 列（缓存命中标记）

Revision ID: 004
Revises: 003
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.add_column(sa.Column("cached", sa.Boolean(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_column("cached")
