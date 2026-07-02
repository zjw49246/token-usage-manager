"""P28：channels 加 success_count/error_count（成功率指标）

Revision ID: 012
Revises: 011
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channels") as batch:
        batch.add_column(sa.Column("success_count", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("error_count", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch:
        batch.drop_column("error_count")
        batch.drop_column("success_count")
