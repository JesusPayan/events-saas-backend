
"""INV-50-01 create logistics orders and items

Revision ID: 8a137f1a4c24
Revises: a9ded70f4c35
"""

from alembic import op
import sqlalchemy as sa


revision = "8a137f1a4c24"
down_revision = "a9ded70f4c35"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "logistics_orders",

        sa.Column(
            "id",
            sa.BigInteger().with_variant(
                sa.Integer(), "sqlite"
            ),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "event_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "status",
            sa.String(20),
            server_default="pending",
            nullable=False,
        ),

        sa.Column(
            "scheduled_at",
            sa.DateTime(),
            nullable=True,
        ),

        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "created_by",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.CheckConstraint(
            "status IN ("
            "'pending', "
            "'in_progress', "
            "'prepared', "
            "'cancelled'"
            ")",
            name="ck_logistics_orders_status",
        ),

        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_logistics_orders_created_by",
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["events.tenant_id", "events.id"],
            name="fk_logistics_orders_event",
        ),

        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_logistics_orders_tenant_id",
        ),
    )

    op.create_index(
        "ix_logistics_orders_tenant_event",
        "logistics_orders",
        ["tenant_id", "event_id"],
    )

    op.create_index(
        "ix_logistics_orders_tenant_status",
        "logistics_orders",
        ["tenant_id", "status"],
    )

    op.create_table(
        "logistics_order_items",

        sa.Column(
            "id",
            sa.BigInteger().with_variant(
                sa.Integer(), "sqlite"
            ),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "logistics_order_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "inventory_item_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "quantity_required",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "quantity_prepared",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.CheckConstraint(
            "quantity_required > 0",
            name="ck_logistics_quantity_required",
        ),

        sa.CheckConstraint(
            "quantity_prepared >= 0 "
            "AND quantity_prepared <= quantity_required",
            name="ck_logistics_quantity_prepared",
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id", "logistics_order_id"],
            [
                "logistics_orders.tenant_id",
                "logistics_orders.id",
            ],
            name="fk_logistics_items_order",
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            [
                "inventory_items.tenant_id",
                "inventory_items.id",
            ],
            name="fk_logistics_items_inventory",
        ),

        sa.UniqueConstraint(
            "tenant_id",
            "logistics_order_id",
            "inventory_item_id",
            name="uq_logistics_order_item",
        ),
    )

    op.create_index(
        "ix_logistics_items_tenant_order",
        "logistics_order_items",
        ["tenant_id", "logistics_order_id"],
    )


def downgrade():
    op.drop_index(
        "ix_logistics_items_tenant_order",
        table_name="logistics_order_items",
    )

    op.drop_table("logistics_order_items")

    op.drop_index(
        "ix_logistics_orders_tenant_status",
        table_name="logistics_orders",
    )

    op.drop_index(
        "ix_logistics_orders_tenant_event",
        table_name="logistics_orders",
    )

    op.drop_table("logistics_orders")
