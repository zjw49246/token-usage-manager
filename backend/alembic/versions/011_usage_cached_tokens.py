"""P27：usage_records 加 cached_tokens（上游 prompt 缓存读 token）

Revision ID: 011
Revises: 010
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.add_column(sa.Column("cached_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_column("cached_tokens")
