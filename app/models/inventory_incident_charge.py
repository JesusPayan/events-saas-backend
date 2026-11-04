
from datetime import datetime, timezone
from app.extensions import db

from decimal import Decimal
from datetime import datetime, date
def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryIncidentCharge(db.Model):
    __tablename__ = "inventory_incident_charges"

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

    event_id = db.Column(
        db.BigInteger,
        nullable=False
    )

    amount = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )

    currency = db.Column(
        db.String(3),
        nullable=False,
        default="MXN",
        server_default="MXN"
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
        server_default="pending"
    )

    description = db.Column(db.Text)

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
    approved_by = db.Column(
    db.BigInteger,
    db.ForeignKey("users.id"),
    nullable=True
)

approved_at = db.Column(db.DateTime, nullable=True)

paid_at = db.Column(db.DateTime, nullable=True)

payment_reference = db.Column(
    db.String(120),
    nullable=True
)

payment_method = db.Column(
    db.String(30),
    nullable=True
)

waived_by = db.Column(
    db.BigInteger,
    db.ForeignKey("users.id"),
    nullable=True
)

waived_at = db.Column(db.DateTime, nullable=True)

resolution_notes = db.Column(db.Text, nullable=True)

__table_args__ = (
        db.ForeignKeyConstraint(
            ["tenant_id", "incident_id"],
            [
                "inventory_incidents.tenant_id",
                "inventory_incidents.id"
            ],
            name="fk_charge_incident_tenant"
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                "events.tenant_id",
                "events.id"
            ],
            name="fk_charge_event_tenant"
        ),
        db.UniqueConstraint(
            "tenant_id",
            "incident_id",
            name="uq_charge_incident"
        ),
        db.CheckConstraint(
            "amount >= 0",
            name="ck_charge_amount_nonnegative"
        ),
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'waived', 'paid')",
            name="ck_charge_status"
        ),
        db.UniqueConstraint(
    "tenant_id",
    "id",
    name="uq_inventory_charge_tenant_id"
),
    )

# def to_dict(self):
#         return {
#             "id": self.id,
#             "tenant_id": self.tenant_id,
#             "incident_id": self.incident_id,
#             "event_id": self.event_id,
#             "amount": str(self.amount),
#             "currency": self.currency,
#             "status": self.status,
#             "description": self.description,
#             "created_by": self.created_by,
#             "created_at": self.created_at.isoformat() + "Z",
#             "approved_by": self.approved_by,
# "approved_at": (
#     self.approved_at.isoformat() + "Z"
#     if self.approved_at else None
# ),
# "paid_at": (
#     self.paid_at.isoformat() + "Z"
#     if self.paid_at else None
# ),
# "payment_reference": self.payment_reference,
# "payment_method": self.payment_method,
# "waived_by": self.waived_by,
# "waived_at": (
#     self.waived_at.isoformat() + "Z"
#     if self.waived_at else None
# ),
# "resolution_notes": self.resolution_notes,
#         }

def to_dict(self):
    return {
        column.name: (
            str(value) if isinstance(value, Decimal)
            else value.isoformat() if isinstance(value, (datetime, date))
            else value
        )
        for column in self.__table__.columns
        for value in [getattr(self, column.name)]
    }