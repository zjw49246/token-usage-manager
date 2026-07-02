"""P20：api_keys 加 allowed_ips（IP 白名单）

Revision ID: 007
Revises: 006
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("allowed_ips", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("allowed_ips")
