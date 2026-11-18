
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
)

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ContractPayment(db.Model):
    __tablename__ = "contract_payments"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(db.BigInteger, nullable=False)
    contract_id = db.Column(db.BigInteger, nullable=False)

    payment_type = db.Column(
        db.String(20),
        nullable=False,
        default="installment",
    )

    amount = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)

    payment_method = db.Column(db.String(30), nullable=False)
    reference = db.Column(db.String(120), nullable=True)

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
    )

    notes = db.Column(db.Text, nullable=True)

    paid_at = db.Column(db.DateTime, nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    created_by = db.Column(db.BigInteger, nullable=False)
    confirmed_by = db.Column(db.BigInteger, nullable=True)

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
            "tenant_id",
            "id",
            name="uq_contract_payments_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "contract_id",
            "reference",
            name="uq_contract_payments_reference",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["contracts.tenant_id", "contracts.id"],
            name="fk_contract_payments_contract_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_contract_payments_created_by",
        ),
        ForeignKeyConstraint(
            ["confirmed_by"],
            ["users.id"],
            name="fk_contract_payments_confirmed_by",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_contract_payments_positive_amount",
        ),
        CheckConstraint(
            "payment_type IN ('advance', 'installment')",
            name="ck_contract_payments_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled')",
            name="ck_contract_payments_status",
        ),
        db.Index(
            "ix_contract_payments_tenant_contract_status",
            "tenant_id",
            "contract_id",
            "status",
        ),
    )
