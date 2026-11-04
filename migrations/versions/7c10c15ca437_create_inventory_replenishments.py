
"""create inventory replenishments

Revision ID: 7c10c15ca437
Revises: fc94a932cabb
"""

from alembic import op
import sqlalchemy as sa


revision = "7c10c15ca437"
down_revision = "fc94a932cabb"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inventory_replenishments",

        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False
        ),

        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False
        ),

        sa.Column(
            "inventory_item_id",
            sa.BigInteger(),
            nullable=False
        ),

        sa.Column(
            "quantity",
            sa.Integer(),
            nullable=False
        ),

        sa.Column(
            "reason",
            sa.Text(),
            nullable=False
        ),

        sa.Column(
            "reference",
            sa.String(length=100),
            nullable=True
        ),

        sa.Column(
            "created_by",
            sa.BigInteger(),
            nullable=False
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False
        ),

        sa.CheckConstraint(
            "quantity > 0",
            name="ck_replenishment_quantity_positive"
        ),

        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"]
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            [
                "inventory_items.tenant_id",
                "inventory_items.id"
            ]
        ),

        sa.PrimaryKeyConstraint("id")
    )


def downgrade():
    op.drop_table("inventory_replenishments")
