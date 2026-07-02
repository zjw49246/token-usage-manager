"""token-router P0：多租户/供应商/模型目录新表 + 旧表加成本与归属列

Revision ID: 002
Revises: 001
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 多租户 ──
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("credit_balance_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_superadmin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("ref", sa.String(100), nullable=True),
        sa.Column("balance_after", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credit_transactions_org_id", "credit_transactions", ["org_id"])
    op.create_index("ix_credit_transactions_created_at", "credit_transactions", ["created_at"])

    # ── 供应商与模型目录 ──
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("litellm_prefix", sa.String(50), nullable=False),
        sa.Column("api_base", sa.String(255), nullable=True),
        sa.Column("credential_env", sa.String(100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_providers_name", "providers", ["name"], unique=True)

    op.create_table(
        "model_catalog",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("model_id", sa.String(150), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("litellm_model", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(150), nullable=True),
        sa.Column("input_price_per_1m", sa.Float(), nullable=True),
        sa.Column("output_price_per_1m", sa.Float(), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_catalog_model_id", "model_catalog", ["model_id"], unique=True)
    op.create_index("ix_model_catalog_provider_id", "model_catalog", ["provider_id"])

    # ── 旧表加列（batch 模式兼容 SQLite）──
    # 注：SQLite 不强制 FK，batch 加列不带内联 FK（避免未命名约束报错）；模型层已定义约束
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("org_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("max_cost_usd", sa.Float(), nullable=True))
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])

    with op.batch_alter_table("usage_records") as batch:
        batch.add_column(sa.Column("org_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("provider", sa.String(50), nullable=True))
        batch.add_column(sa.Column("cost_usd", sa.Float(), nullable=True))
    op.create_index("ix_usage_records_org_id", "usage_records", ["org_id"])

    with op.batch_alter_table("usage_summary") as batch:
        batch.add_column(sa.Column("total_cost_usd", sa.Float(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("usage_summary") as batch:
        batch.drop_column("total_cost_usd")
    op.drop_index("ix_usage_records_org_id", table_name="usage_records")
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_column("cost_usd")
        batch.drop_column("provider")
        batch.drop_column("org_id")
    op.drop_index("ix_api_keys_org_id", table_name="api_keys")
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("max_cost_usd")
        batch.drop_column("created_by_user_id")
        batch.drop_column("org_id")
    op.drop_index("ix_model_catalog_provider_id", table_name="model_catalog")
    op.drop_index("ix_model_catalog_model_id", table_name="model_catalog")
    op.drop_table("model_catalog")
    op.drop_index("ix_providers_name", table_name="providers")
    op.drop_table("providers")
    op.drop_index("ix_credit_transactions_created_at", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_org_id", table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_org_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
