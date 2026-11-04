
from datetime import datetime, timezone

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryReplenishment(db.Model):
    __tablename__ = "inventory_replenishments"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    tenant_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    inventory_item_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        nullable=False
    )

    reason = db.Column(
        db.Text,
        nullable=False
    )

    reference = db.Column(
        db.String(100),
        nullable=True
    )

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
            ["tenant_id", "inventory_item_id"],
            [
                "inventory_items.tenant_id",
                "inventory_items.id"
            ]
        ),
        db.CheckConstraint(
            "quantity > 0",
            name="ck_replenishment_quantity_positive"
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "inventory_item_id": self.inventory_item_id,
            "quantity": self.quantity,
            "reason": self.reason,
            "reference": self.reference,
            "created_by": self.created_by,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            )
        }
