"""P10：memberships 加 budget_usd（成员级预算）

Revision ID: 006
Revises: 005
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memberships") as batch:
        batch.add_column(sa.Column("budget_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch:
        batch.drop_column("budget_usd")
