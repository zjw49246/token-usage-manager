"""移除商业化：organizations.credit_balance_usd / price_multiplier + credit_transactions 表

Revision ID: 013
Revises: 012
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("credit_transactions")
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("price_multiplier")
        batch.drop_column("credit_balance_usd")


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("credit_balance_usd", sa.Float(), server_default="0", nullable=False))
        batch.add_column(sa.Column("price_multiplier", sa.Float(), server_default="1", nullable=False))
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("ref", sa.String(length=100), nullable=True),
        sa.Column("balance_after", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, index=True),
    )
