
from datetime import datetime, timezone
from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Event(db.Model):
    __tablename__ = "events"

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

    client_id = db.Column(
        db.BigInteger,
        db.ForeignKey("clients.id"),
        nullable=False,
        index=True
    )

    name = db.Column(db.String(180), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)

    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)

    location = db.Column(db.String(255), nullable=True)

    status = db.Column(
        db.String(30),
        nullable=False,
        default="draft",
        server_default="draft"
    )

    estimated_guests = db.Column(db.Integer, nullable=True)

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
        db.Index("ix_events_tenant_status", "tenant_id", "status"),
        db.Index("ix_events_tenant_starts", "tenant_id", "starts_at"),
        db.UniqueConstraint(
    "tenant_id",
    "id",
    name="uq_events_tenant_id"
),

db.UniqueConstraint(
    "tenant_id",
    "id",
    "client_id",
    name="uq_events_tenant_id_client"
)
    )

    def to_dict(self):
        def iso(dt):
            return dt.isoformat() + "Z" if dt else None

        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "name": self.name,
            "event_type": self.event_type,
            "description": self.description,
            "starts_at": iso(self.starts_at),
            "ends_at": iso(self.ends_at),
            "location": self.location,
            "status": self.status,
            "estimated_guests": self.estimated_guests,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at)
        }
