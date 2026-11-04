
from datetime import datetime, timezone

from app.extensions import db
from sqlalchemy import ForeignKeyConstraint


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class QuoteStatusHistory(db.Model):
    __tablename__ = "quote_status_history"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    quote_id = db.Column(db.BigInteger, nullable=False)

    previous_status = db.Column(db.String(20), nullable=True)
    new_status = db.Column(db.String(20), nullable=False)

    notes = db.Column(db.Text, nullable=True)

    changed_by = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_status_history_quote_tenant",
        ),
        db.Index(
            "ix_quote_status_history_tenant_quote",
            "tenant_id",
            "quote_id",
        ),
    )

    quote = db.relationship(
        "Quote",
        back_populates="status_history",
        foreign_keys=[tenant_id, quote_id],
    )

