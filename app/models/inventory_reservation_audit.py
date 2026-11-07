
from datetime import datetime, timezone

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryReservationAudit(db.Model):
    __tablename__ = "inventory_reservation_audits"

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(
        db.BigInteger,
        nullable=False,
    )

    reservation_id = db.Column(
        db.BigInteger,
        nullable=False,
    )

    action = db.Column(
        db.String(30),
        nullable=False,
    )

    previous_quantity = db.Column(
        db.Integer,
        nullable=True,
    )

    new_quantity = db.Column(
        db.Integer,
        nullable=True,
    )

    previous_status = db.Column(
        db.String(20),
        nullable=True,
    )

    new_status = db.Column(
        db.String(20),
        nullable=False,
    )

    changed_by = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id"),
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            [
                "inventory_reservations.tenant_id",
                "inventory_reservations.id",
            ],
            name="fk_reservation_audit_tenant",
        ),
        db.Index(
            "ix_reservation_audit_tenant_reservation",
            "tenant_id",
            "reservation_id",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "reservation_id": self.reservation_id,
            "action": self.action,
            "previous_quantity": self.previous_quantity,
            "new_quantity": self.new_quantity,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "changed_by": self.changed_by,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            ),
        }
