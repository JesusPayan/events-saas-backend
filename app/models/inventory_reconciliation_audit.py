
from datetime import datetime, timezone
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryReconciliationAudit(db.Model):
    __tablename__ = "inventory_reconciliation_audits"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.BigInteger, db.ForeignKey("tenants.id"), nullable=False
    )
    incident_id = db.Column(db.BigInteger, nullable=False)
    inventory_item_id = db.Column(db.BigInteger, nullable=False)
    adjustment_type = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    quantity_total_before = db.Column(db.Integer, nullable=False)
    quantity_total_after = db.Column(db.Integer, nullable=False)
    unavailable_before = db.Column(db.Integer, nullable=False)
    unavailable_after = db.Column(db.Integer, nullable=False)
    capacity_before = db.Column(db.Integer, nullable=False)
    capacity_after = db.Column(db.Integer, nullable=False)
    max_reserved = db.Column(db.Integer, nullable=False)
    shortage_after = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    total_cost = db.Column(db.Numeric(12, 2), nullable=False)
    accepted_deficit = db.Column(db.Boolean, nullable=False, default=False)
    reason = db.Column(db.Text, nullable=True)
    created_by = db.Column(
        db.BigInteger, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "incident_id",
            name="uq_reconciliation_audit_incident"
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "incident_id"],
            ["inventory_incidents.tenant_id", "inventory_incidents.id"]
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"]
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "inventory_item_id": self.inventory_item_id,
            "adjustment_type": self.adjustment_type,
            "quantity": self.quantity,
            "quantity_total_before": self.quantity_total_before,
            "quantity_total_after": self.quantity_total_after,
            "unavailable_before": self.unavailable_before,
            "unavailable_after": self.unavailable_after,
            "capacity_before": self.capacity_before,
            "capacity_after": self.capacity_after,
            "max_reserved": self.max_reserved,
            "shortage_after": self.shortage_after,
            "unit_cost": str(self.unit_cost),
            "total_cost": str(self.total_cost),
            "accepted_deficit": self.accepted_deficit,
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            ),
        }
