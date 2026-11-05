
from datetime import datetime, timezone
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryCapacityAlert(db.Model):
    __tablename__ = "inventory_capacity_alerts"

    id = db.Column(
            db.BigInteger().with_variant(db.Integer, "sqlite"),
            primary_key=True,
            autoincrement=True
            )
    tenant_id = db.Column(
        db.BigInteger, db.ForeignKey("tenants.id"), nullable=False
    )
    inventory_item_id = db.Column(db.BigInteger, nullable=False)
    reservation_id = db.Column(db.BigInteger, nullable=False)
    required_quantity = db.Column(db.Integer, nullable=False)
    available_quantity = db.Column(db.Integer, nullable=False)
    shortage_quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(
        db.String(20), nullable=False, default="open"
    )
    detected_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(
        db.DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "inventory_item_id", "reservation_id",
            name="uq_capacity_alert_reservation"
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"]
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["inventory_reservations.tenant_id", "inventory_reservations.id"]
        ),
        db.CheckConstraint(
            "shortage_quantity > 0", name="ck_capacity_shortage_positive"
        ),
        db.UniqueConstraint(
    "tenant_id",
    "id",
    name="uq_capacity_alert_tenant_id"
),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "inventory_item_id": self.inventory_item_id,
            "reservation_id": self.reservation_id,
            "required_quantity": self.required_quantity,
            "available_quantity": self.available_quantity,
            "shortage_quantity": self.shortage_quantity,
            "status": self.status,
            "detected_at": (
                self.detected_at.isoformat() + "Z"
                if self.detected_at else None
            ),
            "resolved_at": (
                self.resolved_at.isoformat() + "Z"
                if self.resolved_at else None
            ),
        }
