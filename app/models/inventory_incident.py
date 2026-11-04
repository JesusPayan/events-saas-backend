
from datetime import datetime, timezone

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryIncident(db.Model):
    __tablename__ = "inventory_incidents"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    tenant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("tenants.id"),
        nullable=False,
        index=True
    )

    reservation_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    inventory_item_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    incident_type = db.Column(
        db.String(20),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=False
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="reported",
        server_default="reported"
    )

    unit_cost = db.Column(
        db.Numeric(12, 2),
        nullable=True
    )

    total_cost = db.Column(
        db.Numeric(12, 2),
        nullable=True
    )

    reported_by = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now
    )

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            [
                "inventory_reservations.tenant_id",
                "inventory_reservations.id"
            ],
            name="fk_incident_reservation_tenant"
        ),

        db.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            [
                "inventory_items.tenant_id",
                "inventory_items.id"
            ],
            name="fk_incident_item_tenant"
        ),

        db.CheckConstraint(
            "quantity > 0",
            name="ck_incident_positive_quantity"
        ),

        db.CheckConstraint(
            "incident_type IN ('damaged', 'lost', 'missing')",
            name="ck_incident_type"
        ),

        db.CheckConstraint(
            "status IN ('reported', 'assessed', 'resolved', 'cancelled')",
            name="ck_incident_status"
        ),

        db.CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0",
            name="ck_incident_unit_cost"
        ),

        db.CheckConstraint(
            "total_cost IS NULL OR total_cost >= 0",
            name="ck_incident_total_cost"
        ),

        db.Index(
            "ix_incidents_tenant_reservation",
            "tenant_id",
            "reservation_id"
        ),

        db.Index(
            "ix_incidents_tenant_status",
            "tenant_id",
            "status"
        ),

        db.UniqueConstraint(
    "tenant_id",
    "id",
    name="uq_inventory_incident_tenant_id"
),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "reservation_id": self.reservation_id,
            "inventory_item_id": self.inventory_item_id,
            "incident_type": self.incident_type,
            "quantity": self.quantity,
            "description": self.description,
            "status": self.status,
            "unit_cost": (
                str(self.unit_cost)
                if self.unit_cost is not None else None
            ),
            "total_cost": (
                str(self.total_cost)
                if self.total_cost is not None else None
            ),
            "reported_by": self.reported_by,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() + "Z"
                if self.updated_at else None
            )
        }
