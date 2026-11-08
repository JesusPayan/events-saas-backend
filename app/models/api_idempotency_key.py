
from datetime import datetime, timezone

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ApiIdempotencyKey(db.Model):
    __tablename__ = "api_idempotency_keys"

    id = db.Column(
        db.BigInteger().with_variant(db.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("tenants.id"),
        nullable=False,
    )

    operation = db.Column(
        db.String(100),
        nullable=False,
    )

    idempotency_key = db.Column(
        db.String(128),
        nullable=False,
    )

    request_hash = db.Column(
        db.String(64),
        nullable=False,
    )

    response_status = db.Column(
        db.Integer,
        nullable=True,
    )

    response_body = db.Column(
        db.JSON,
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id",
            "operation",
            "idempotency_key",
            name="uq_api_idempotency_tenant_operation_key",
        ),
        db.Index(
            "ix_api_idempotency_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )
