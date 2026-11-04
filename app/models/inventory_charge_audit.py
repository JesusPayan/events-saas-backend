
from datetime import datetime, timezone
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryChargeAudit(db.Model):
    __tablename__ = "inventory_charge_audits"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    tenant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("tenants.id"),
        nullable=False
    )

    charge_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    previous_status = db.Column(
        db.String(20),
        nullable=False
    )

    new_status = db.Column(
        db.String(20),
        nullable=False
    )

    notes = db.Column(db.Text)

    changed_by = db.Column(
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
            ["tenant_id", "charge_id"],
            [
                "inventory_incident_charges.tenant_id",
                "inventory_incident_charges.id"
            ],
            name="fk_charge_audit_tenant"
        ),
        db.Index(
            "ix_charge_audit_tenant_charge",
            "tenant_id",
            "charge_id"
        )
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "charge_id": self.charge_id,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "notes": self.notes,
            "changed_by": self.changed_by,
            "created_at": (
                self.created_at.isoformat() + "Z"
                if self.created_at else None
            )
        }
