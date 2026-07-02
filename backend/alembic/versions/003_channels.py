"""P6：上游通道表（负载均衡 + 故障转移）

Revision ID: 003
Revises: 002
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("api_key", sa.String(255), nullable=True),
        sa.Column("api_base", sa.String(255), nullable=True),
        sa.Column("models", sa.JSON(), nullable=True),
        sa.Column("model_map", sa.JSON(), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_channels_provider_id", "channels", ["provider_id"])


def downgrade() -> None:
    op.drop_index("ix_channels_provider_id", table_name="channels")
    op.drop_table("channels")
