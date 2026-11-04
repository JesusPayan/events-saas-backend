
from datetime import datetime, timezone
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"

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

    inventory_item_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    reservation_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    movement_type = db.Column(
        db.String(20),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        nullable=False
    )

    notes = db.Column(db.Text, nullable=True)

    created_by = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now
    )

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            [
                "inventory_reservations.tenant_id",
                "inventory_reservations.id"
            ],
            name="fk_movement_reservation_tenant"
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            [
                "inventory_items.tenant_id",
                "inventory_items.id"
            ],
            name="fk_movement_item_tenant"
        ),
        db.CheckConstraint(
            "quantity > 0",
            name="ck_movement_positive_quantity"
        ),
        db.CheckConstraint(
            "movement_type IN ('dispatch', 'return')",
            name="ck_movement_type"
        ),
        db.Index(
            "ix_movements_reservation_type",
            "reservation_id",
            "movement_type"
        )
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "inventory_item_id": self.inventory_item_id,
            "reservation_id": self.reservation_id,
            "movement_type": self.movement_type,
            "quantity": self.quantity,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            )
        }
