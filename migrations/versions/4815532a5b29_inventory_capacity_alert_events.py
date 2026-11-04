
"""inventory capacity alert events

Revision ID: 4815532a5b29
Revises: 7c10c15ca437
"""

from alembic import op
import sqlalchemy as sa


revision = "4815532a5b29"
down_revision = "7c10c15ca437"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_capacity_alert_tenant_id",
        "inventory_capacity_alerts",
        ["tenant_id", "id"]
    )

    op.create_table(
        "inventory_capacity_alert_events",

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
            "alert_id",
            sa.BigInteger(),
            nullable=False
        ),

        sa.Column(
            "action",
            sa.String(length=20),
            nullable=False
        ),

        sa.Column(
            "previous_shortage",
            sa.Integer(),
            nullable=False
        ),

        sa.Column(
            "new_shortage",
            sa.Integer(),
            nullable=False
        ),

        sa.Column(
            "source_type",
            sa.String(length=30),
            nullable=False
        ),

        sa.Column(
            "source_id",
            sa.BigInteger(),
            nullable=True
        ),

        sa.Column(
            "created_by",
            sa.BigInteger(),
            nullable=True
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False
        ),

        sa.CheckConstraint(
            "action IN ('opened', 'updated', 'resolved', 'reopened')",
            name="ck_capacity_event_action"
        ),

        sa.CheckConstraint(
            "previous_shortage >= 0 AND new_shortage >= 0",
            name="ck_capacity_event_shortage"
        ),

        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"]
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id", "alert_id"],
            [
                "inventory_capacity_alerts.tenant_id",
                "inventory_capacity_alerts.id"
            ],
            name="fk_capacity_event_alert_tenant"
        ),

        sa.PrimaryKeyConstraint("id")
    )

    op.create_index(
        "ix_capacity_event_tenant_alert",
        "inventory_capacity_alert_events",
        ["tenant_id", "alert_id", "created_at"],
        unique=False
    )


def downgrade():
    op.drop_index(
        "ix_capacity_event_tenant_alert",
        table_name="inventory_capacity_alert_events"
    )

    op.drop_table(
        "inventory_capacity_alert_events"
    )

    op.drop_constraint(
        "uq_capacity_alert_tenant_id",
        "inventory_capacity_alerts",
        type_="unique"
    )
