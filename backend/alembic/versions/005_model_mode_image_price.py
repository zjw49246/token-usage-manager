"""P8：model_catalog 加 mode + image_price（embeddings / image 端点）

Revision ID: 005
Revises: 004
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_catalog") as batch:
        batch.add_column(sa.Column("mode", sa.String(30), server_default="chat", nullable=False))
        batch.add_column(sa.Column("image_price", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("model_catalog") as batch:
        batch.drop_column("image_price")
        batch.drop_column("mode")
