
from datetime import datetime, timezone

from app.extensions import db
from sqlalchemy import ForeignKeyConstraint


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ContractStatusHistory(db.Model):
    __tablename__ = "contract_status_history"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    tenant_id = db.Column(db.BigInteger, nullable=False)
    contract_id = db.Column(db.BigInteger, nullable=False)

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
            ["tenant_id", "contract_id"],
            ["contracts.tenant_id", "contracts.id"],
            name="fk_contract_history_contract_tenant",
        ),
        ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_contract_history_changed_by",
        ),
        db.Index(
            "ix_contract_history_tenant_contract",
            "tenant_id",
            "contract_id",
        ),
    )
