
from datetime import datetime, timezone

from app.extensions import db
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(db.BigInteger, nullable=False)
    quote_id = db.Column(db.BigInteger, nullable=False)
    event_id = db.Column(db.BigInteger, nullable=False)
    client_id = db.Column(db.BigInteger, nullable=False)

    contract_number = db.Column(db.String(40), nullable=False)

    status = db.Column(
        db.String(20),
        nullable=False,
        default="draft",
    )

    currency = db.Column(
        db.String(3),
        nullable=False,
        default="MXN",
    )

    subtotal = db.Column(db.Numeric(14, 2), nullable=False)
    discount_total = db.Column(db.Numeric(14, 2), nullable=False)
    tax_total = db.Column(db.Numeric(14, 2), nullable=False)
    total = db.Column(db.Numeric(14, 2), nullable=False)

    notes = db.Column(db.Text, nullable=True)
    terms_conditions = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id",
            name="uq_contracts_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id", "quote_id",
            name="uq_contracts_tenant_quote",
        ),
        UniqueConstraint(
            "tenant_id", "contract_number",
            name="uq_contracts_tenant_number",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_contracts_quote_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "client_id"],
            ["events.tenant_id", "events.id", "events.client_id"],
            name="fk_contracts_event_client_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_contracts_created_by",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'cancelled')",
            name="ck_contracts_status",
        ),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 "
            "AND tax_total >= 0 AND total >= 0",
            name="ck_contracts_amounts",
        ),
        db.Index(
            "ix_contracts_tenant_status",
            "tenant_id",
            "status",
        ),
        db.Index(
            "ix_contracts_tenant_event",
            "tenant_id",
            "event_id",
        ),
    )
