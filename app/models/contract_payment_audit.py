
from datetime import datetime, timezone

from sqlalchemy import ForeignKeyConstraint

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ContractPaymentAudit(db.Model):
    __tablename__ = "contract_payment_audits"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(db.BigInteger, nullable=False)
    payment_id = db.Column(db.BigInteger, nullable=False)

    action = db.Column(db.String(30), nullable=False)
    previous_status = db.Column(db.String(20), nullable=True)
    new_status = db.Column(db.String(20), nullable=False)

    notes = db.Column(db.Text, nullable=True)

    changed_by = db.Column(db.BigInteger, nullable=False)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            [
                "contract_payments.tenant_id",
                "contract_payments.id",
            ],
            name="fk_contract_payment_audits_payment_tenant",
        ),
        ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_contract_payment_audits_changed_by",
        ),
        db.Index(
            "ix_contract_payment_audits_tenant_payment",
            "tenant_id",
            "payment_id",
        ),
    )
