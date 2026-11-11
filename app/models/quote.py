
from datetime import datetime, timezone

from app.extensions import db
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from datetime import datetime, timezone

from app.models.quote_status_history import QuoteStatusHistory
from app.services.quote_validation import QuoteValidationError

from app.models.quote_status_history import QuoteStatusHistory


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Quote(db.Model):
    __tablename__ = "quotes"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    event_id = db.Column(db.BigInteger, nullable=False)
    client_id = db.Column(db.BigInteger, nullable=False)

    quote_number = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    currency = db.Column(db.String(3), nullable=False, default="MXN")
    valid_until = db.Column(db.Date, nullable=True)

    subtotal = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    discount_total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    tax_total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    notes = db.Column(db.Text, nullable=True)
    terms_conditions = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id",
            name="uq_quotes_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id", "quote_number",
            name="uq_quotes_tenant_number",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_quotes_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "client_id"],
            ["clients.tenant_id", "clients.id"],
            name="fk_quotes_client_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "client_id"],
            ["events.tenant_id", "events.id", "events.client_id"],
            name="fk_quotes_event_client_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_quotes_created_by",
        ),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 "
            "AND tax_total >= 0 AND total >= 0",
            name="ck_quotes_amounts_nonnegative",
        ),
        db.Index("ix_quotes_tenant_status", "tenant_id", "status"),
        db.Index("ix_quotes_tenant_event", "tenant_id", "event_id"),
        db.Index("ix_quotes_tenant_client", "tenant_id", "client_id"),
    )

    items = db.relationship(
        "QuoteItem",
        back_populates="quote",
        cascade="all, delete-orphan",
        foreign_keys="[QuoteItem.tenant_id, QuoteItem.quote_id]",
    )

    versions = db.relationship(
        "QuoteVersion",
        back_populates="quote",
        cascade="all, delete-orphan",
        foreign_keys="[QuoteVersion.tenant_id, QuoteVersion.quote_id]",
    )

    status_history = db.relationship(
        "QuoteStatusHistory",
        back_populates="quote",
        cascade="all, delete-orphan",
        foreign_keys="[QuoteStatusHistory.tenant_id, QuoteStatusHistory.quote_id]",
    )

#     db.CheckConstraint(
#     "status IN ("
#     "'draft', 'sent', 'accepted', "
#     "'rejected', 'expired', 'cancelled', 'converted'"
#     ")",
#     name='ck_quotes_status'
# )





QUOTE_TRANSITIONS = {
    "draft": {"sent", "cancelled"},
    "sent": {"accepted", "rejected", "expired", "cancelled"},
    "accepted": set(),
    "rejected": set(),
    "expired": set(),
    "cancelled": set(),
    "converted": set(),
}


def change_quote_status(
    tenant_id: int,
    quote_id: int,
    user_id: int,
    new_status: str,
    notes: str | None = None,
):
    if not isinstance(new_status, str):
        raise QuoteValidationError({
            "status": "invalid_status"
        })

    if notes is not None and (
        not isinstance(notes, str) or len(notes) > 2000
    ):
        raise QuoteValidationError({
            "notes": "invalid_notes"
        })

    quote = db.session.scalar(
        select(Quote)
        .where(
            Quote.id == quote_id,
            Quote.tenant_id == tenant_id,
        )
        .with_for_update()
    )

    if quote is None:
        raise QuoteValidationError(
            {"quote": "not_found"},
            status_code=404,
        )

    previous_status = quote.status
    allowed = QUOTE_TRANSITIONS.get(previous_status, set())

    if new_status not in allowed:
        raise QuoteValidationError(
            {
                "status": "invalid_transition",
                "current_status": previous_status,
                "requested_status": new_status,
            },
            status_code=409,
        )

    if (
        new_status == "sent"
        and quote.valid_until is not None
        and quote.valid_until < datetime.now(
            timezone.utc
        ).date()
    ):
        raise QuoteValidationError(
            {"valid_until": "quote_expired"},
            status_code=409,
        )

    quote.status = new_status

    db.session.add(
        QuoteStatusHistory(
            tenant_id=tenant_id,
            quote_id=quote.id,
            previous_status=previous_status,
            new_status=new_status,
            changed_by=user_id,
            notes=notes.strip() if notes else None,
        )
    )

    db.session.flush()

    return quote