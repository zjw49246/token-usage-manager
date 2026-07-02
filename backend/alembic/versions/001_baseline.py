"""baseline: 原有 3 表（api_keys / usage_records / usage_summary）

已有部署（此前由 create_all 建库）请先执行 `alembic stamp 001` 再 upgrade。

Revision ID: 001
Revises:
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("allowed_models", sa.JSON(), nullable=True),
        sa.Column("max_total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("max_calls", sa.Integer(), nullable=True),
        sa.Column("max_rpm", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "usage_records",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("api_key_id", sa.Integer(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_usage_records_api_key_id", "usage_records", ["api_key_id"])
    op.create_index("ix_usage_records_created_at", "usage_records", ["created_at"])

    op.create_table(
        "usage_summary",
        sa.Column("api_key_id", sa.Integer(), sa.ForeignKey("api_keys.id"), primary_key=True),
        sa.Column("total_tokens_used", sa.BigInteger(), nullable=False),
        sa.Column("total_calls", sa.Integer(), nullable=False),
        sa.Column("last_call_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("usage_summary")
    op.drop_index("ix_usage_records_created_at", table_name="usage_records")
    op.drop_index("ix_usage_records_api_key_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")
