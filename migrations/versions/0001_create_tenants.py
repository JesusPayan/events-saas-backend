"""Create tenants base table.

Revision ID: 0001_create_tenants
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_create_tenants"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )


def downgrade():
    op.drop_table("tenants")
