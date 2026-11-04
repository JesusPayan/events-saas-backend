
from datetime import datetime, timezone

from app.extensions import db
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class QuoteVersion(db.Model):
    __tablename__ = "quote_versions"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    quote_id = db.Column(db.BigInteger, nullable=False)

    version_number = db.Column(db.Integer, nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)

    created_by = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "quote_id", "version_number",
            name="uq_quote_versions_number",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_versions_quote_tenant",
        ),
        db.Index("ix_quote_versions_tenant_quote", "tenant_id", "quote_id"),
    )

    quote = db.relationship(
        "Quote",
        back_populates="versions",
        foreign_keys=[tenant_id, quote_id],
    )
