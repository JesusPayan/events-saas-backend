
"""INV-50-04 dispatch, delivery and status history.

Revision ID: b7e504000001
Revises: 8a137f1a4c24
"""

from alembic import op
import sqlalchemy as sa


revision = "b7e504000001"
down_revision = "8a137f1a4c24"
branch_labels = None
depends_on = None


def upgrade():

    # 1. Datos de despacho
    op.add_column(
        "logistics_orders",
        sa.Column("dispatched_at", sa.DateTime(), nullable=True),
    )

    op.add_column(
        "logistics_orders",
        sa.Column("dispatched_by", sa.BigInteger(), nullable=True),
    )

    op.add_column(
        "logistics_orders",
        sa.Column("dispatch_notes", sa.Text(), nullable=True),
    )

    # 2. Datos de entrega
    op.add_column(
        "logistics_orders",
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
    )

    op.add_column(
        "logistics_orders",
        sa.Column("delivered_by", sa.BigInteger(), nullable=True),
    )

    op.add_column(
        "logistics_orders",
        sa.Column("delivery_notes", sa.Text(), nullable=True),
    )

    # 3. Claves foráneas
    op.create_foreign_key(
        "fk_logistics_orders_dispatched_by",
        "logistics_orders",
        "users",
        ["dispatched_by"],
        ["id"],
    )

    op.create_foreign_key(
        "fk_logistics_orders_delivered_by",
        "logistics_orders",
        "users",
        ["delivered_by"],
        ["id"],
    )

    # 4. Ampliar estados permitidos
    op.drop_constraint(
        "ck_logistics_orders_status",
        "logistics_orders",
        type_="check",
    )

    op.create_check_constraint(
        "ck_logistics_orders_status",
        "logistics_orders",
        "status IN ("
        "'pending', "
        "'in_progress', "
        "'prepared', "
        "'dispatched', "
        "'delivered', "
        "'cancelled'"
        ")",
    )

    # 5. Historial logístico
    op.create_table(
        "logistics_order_status_history",

        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("logistics_order_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("changed_by", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),

        sa.ForeignKeyConstraint(
            ["tenant_id", "logistics_order_id"],
            ["logistics_orders.tenant_id", "logistics_orders.id"],
            name="fk_logistics_history_order",
        ),

        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_logistics_history_user",
        ),
    )

    op.create_index(
        "ix_logistics_history_tenant_order",
        "logistics_order_status_history",
        ["tenant_id", "logistics_order_id"],
    )


def downgrade():

    # No permitir downgrade con órdenes en estados nuevos.
    connection = op.get_bind()

    count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM logistics_orders "
            "WHERE status IN ('dispatched', 'delivered')"
        )
    ).scalar()

    if count:
        raise RuntimeError(
            "No se puede revertir: existen órdenes "
            "despachadas o entregadas."
        )

    op.drop_index(
        "ix_logistics_history_tenant_order",
        table_name="logistics_order_status_history",
    )

    op.drop_table("logistics_order_status_history")

    op.drop_constraint(
        "ck_logistics_orders_status",
        "logistics_orders",
        type_="check",
    )

    op.create_check_constraint(
        "ck_logistics_orders_status",
        "logistics_orders",
        "status IN ("
        "'pending', "
        "'in_progress', "
        "'prepared', "
        "'cancelled'"
        ")",
    )

    op.drop_constraint(
        "fk_logistics_orders_delivered_by",
        "logistics_orders",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_logistics_orders_dispatched_by",
        "logistics_orders",
        type_="foreignkey",
    )

    for column in (
        "delivery_notes",
        "delivered_by",
        "delivered_at",
        "dispatch_notes",
        "dispatched_by",
        "dispatched_at",
    ):
        op.drop_column("logistics_orders", column)
