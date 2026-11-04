
from datetime import datetime, timezone

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryCapacityAlertEvent(db.Model):
    __tablename__ = "inventory_capacity_alert_events"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    tenant_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    alert_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    action = db.Column(
        db.String(20),
        nullable=False
    )

    previous_shortage = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    new_shortage = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    source_type = db.Column(
        db.String(30),
        nullable=False,
        default="system"
    )

    source_id = db.Column(
        db.BigInteger,
        nullable=True
    )

    created_by = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id"),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now
    )

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["tenant_id", "alert_id"],
            [
                "inventory_capacity_alerts.tenant_id",
                "inventory_capacity_alerts.id"
            ],
            name="fk_capacity_event_alert_tenant"
        ),
        db.CheckConstraint(
            "action IN ('opened', 'updated', 'resolved', 'reopened')",
            name="ck_capacity_event_action"
        ),
        db.CheckConstraint(
            "previous_shortage >= 0 AND new_shortage >= 0",
            name="ck_capacity_event_shortage"
        ),
        db.Index(
            "ix_capacity_event_tenant_alert",
            "tenant_id",
            "alert_id",
            "created_at"
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "alert_id": self.alert_id,
            "action": self.action,
            "previous_shortage": self.previous_shortage,
            "new_shortage": self.new_shortage,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "created_by": self.created_by,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            )
        }
