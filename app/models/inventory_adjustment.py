
from datetime import datetime, timezone
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryAdjustment(db.Model):
    __tablename__ = "inventory_adjustments"

    id = db.Column(db.BigInteger, primary_key=True)

    tenant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("tenants.id"),
        nullable=False
    )

    incident_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    inventory_item_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    adjustment_type = db.Column(
        db.String(30),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        nullable=False
    )

    reason = db.Column(db.Text, nullable=False)

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
            ["tenant_id", "incident_id"],
            [
                "inventory_incidents.tenant_id",
                "inventory_incidents.id"
            ],
            name="fk_adjustment_incident_tenant"
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            [
                "inventory_items.tenant_id",
                "inventory_items.id"
            ],
            name="fk_adjustment_item_tenant"
        ),
        db.UniqueConstraint(
            "tenant_id",
            "incident_id",
            name="uq_adjustment_incident"
        ),
        db.CheckConstraint(
            "quantity > 0",
            name="ck_adjustment_positive_quantity"
        ),
        db.CheckConstraint(
            "adjustment_type IN ('loss', 'quarantine')",
            name="ck_adjustment_type"
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "incident_id": self.incident_id,
            "inventory_item_id": self.inventory_item_id,
            "adjustment_type": self.adjustment_type,
            "quantity": self.quantity,
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() + "Z"
        }
