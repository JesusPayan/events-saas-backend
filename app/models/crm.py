
from datetime import datetime, timezone
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc)


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    tenant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("tenants.id"),
        nullable=False,
        index=True
    )

    client_type = db.Column(
        db.String(20),
        nullable=False,
        default="individual"
    )

    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(150), nullable=True)

    business_name = db.Column(db.String(180), nullable=True)

    email = db.Column(db.String(180), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    whatsapp = db.Column(db.String(30), nullable=True)

    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    postal_code = db.Column(db.String(15), nullable=True)

    notes = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.String(20),
        nullable=False,
        default="active"
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now
    )

    __table_args__ = (
        db.Index("ix_clients_tenant_status", "tenant_id", "status"),
        db.Index("ix_clients_tenant_email", "tenant_id", "email"),
        db.UniqueConstraint(
    "tenant_id",
    "id",
    name="uq_clients_tenant_id"
)
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "client_type": self.client_type,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "business_name": self.business_name,
            "email": self.email,
            "phone": self.phone,
            "whatsapp": self.whatsapp,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "notes": self.notes,
            "status": self.status,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if self.updated_at else None
            ),
        }
