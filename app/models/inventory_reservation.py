
from datetime import datetime, timezone

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryReservation(db.Model):
    __tablename__ = "inventory_reservations"

    id = db.Column(
    db.BigInteger().with_variant(db.Integer, "sqlite"),
    primary_key=True,
    autoincrement=True
)

    tenant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("tenants.id"),
        nullable=False,
        index=True
    )

    event_id = db.Column(
        db.BigInteger,
        db.ForeignKey("events.id"),
        nullable=False,
        index=True
    )

    inventory_item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("inventory_items.id"),
        nullable=False,
        index=True
    )

    quantity = db.Column(
        db.Integer,
        nullable=False
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="reserved",
        server_default="reserved"
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
        db.UniqueConstraint(
            "tenant_id",
            "event_id",
            "inventory_item_id",
            name="uq_reservation_event_item"
        ),
        db.CheckConstraint(
            "quantity > 0",
            name="ck_reservation_quantity_positive"
        ),
        db.Index(
            "ix_reservation_tenant_item_status",
            "tenant_id",
            "inventory_item_id",
            "status"
        ),
        db.UniqueConstraint(
    "tenant_id",
    "id",
    name="uq_inventory_reservation_tenant_id"
),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "event_id": self.event_id,
            "inventory_item_id": self.inventory_item_id,
            "quantity": self.quantity,
            "status": self.status,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() + "Z"
                if self.updated_at else None
            )
        }
