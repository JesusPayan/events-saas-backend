"""capacity deficit alerts and reconciliation audit

Revision ID: fc94a932cabb
Revises: 379533853b76
"""
from alembic import op
import sqlalchemy as sa

revision = "fc94a932cabb"
down_revision = "379533853b76"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    expected = {"inventory_capacity_alerts", "inventory_reconciliation_audits"}
    present = existing & expected

    # MySQL DDL can commit even when a subsequent Alembic operation fails.
    # Never silently treat preexisting tables as matching the migration.
    if present:
        raise RuntimeError(
            "Migration fc94a932cabb found preexisting table(s): "
            + ", ".join(sorted(present))
            + ". Inspect SHOW CREATE TABLE for each and reconcile the "
              "partial migration before rerunning; do not drop tables blindly."
        )

    op.create_table(
        "inventory_capacity_alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("required_quantity", sa.Integer(), nullable=False),
        sa.Column("available_quantity", sa.Integer(), nullable=False),
        sa.Column("shortage_quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("shortage_quantity > 0", name="ck_capacity_shortage_positive"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["inventory_reservations.tenant_id", "inventory_reservations.id"],
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "inventory_item_id", "reservation_id",
            name="uq_capacity_alert_reservation",
        ),
    )

    op.create_table(
        "inventory_reconciliation_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("incident_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_type", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("quantity_total_before", sa.Integer(), nullable=False),
        sa.Column("quantity_total_after", sa.Integer(), nullable=False),
        sa.Column("unavailable_before", sa.Integer(), nullable=False),
        sa.Column("unavailable_after", sa.Integer(), nullable=False),
        sa.Column("capacity_before", sa.Integer(), nullable=False),
        sa.Column("capacity_after", sa.Integer(), nullable=False),
        sa.Column("max_reserved", sa.Integer(), nullable=False),
        sa.Column("shortage_after", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_cost", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("accepted_deficit", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "incident_id"],
            ["inventory_incidents.tenant_id", "inventory_incidents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "incident_id", name="uq_reconciliation_audit_incident"
        ),
    )


def downgrade():
    op.drop_table("inventory_reconciliation_audits")
    op.drop_table("inventory_capacity_alerts")
