
from uuid import uuid4
from decimal import Decimal
from sqlalchemy import select

from app.extensions import db
from app.models.quote import Quote
from app.models.quote_item import QuoteItem
from app.models.quote_status_history import QuoteStatusHistory
from app.services.quote_calculator import money
from app.services.quote_validation import (
    validate_quote,
    QuoteValidationError,
)


def serialize_item(item):
    return {
        "id": item.id,
        "inventory_item_id": item.inventory_item_id,
        "item_type": item.item_type,
        "description": item.description,
        "quantity": str(item.quantity),
        "unit_price": str(item.unit_price),
        "discount_amount": str(item.discount_amount),
        "tax_rate": str(item.tax_rate),
        "subtotal": str(item.subtotal),
        "tax_amount": str(item.tax_amount),
        "total": str(item.total),
        "sort_order": item.sort_order,
    }


def serialize_quote(quote, include_items=False):
    result = {
        "id": quote.id,
        "tenant_id": quote.tenant_id,
        "client_id": quote.client_id,
        "event_id": quote.event_id,
        "quote_number": quote.quote_number,
        "status": quote.status,
        "currency": quote.currency,
        "valid_until": (
            quote.valid_until.isoformat()
            if quote.valid_until else None
        ),
        "subtotal": str(quote.subtotal),
        "discount_total": str(quote.discount_total),
        "tax_total": str(quote.tax_total),
        "total": str(quote.total),
        "notes": quote.notes,
        "terms_conditions": quote.terms_conditions,
        "created_by": quote.created_by,
        "created_at": (
            quote.created_at.isoformat()
            if quote.created_at else None
        ),
        "updated_at": (
            quote.updated_at.isoformat()
            if quote.updated_at else None
        ),
    }

    if include_items:
        result["items"] = [
            serialize_item(item)
            for item in sorted(
                quote.items,
                key=lambda row: (row.sort_order, row.id)
            )
        ]

    return result


def get_quote(tenant_id, quote_id):
    return db.session.scalar(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.tenant_id == tenant_id
        )
    )


def create_quote(tenant_id, user_id, data):
    cleaned = validate_quote(data, tenant_id)
    items = cleaned.pop("items")

    subtotal = money(sum(
        (item["subtotal"] for item in items),
        Decimal("0.00")
    ))
    discount_total = money(sum(
        (item["discount_amount"] for item in items),
        Decimal("0.00")
    ))
    tax_total = money(sum(
        (item["tax_amount"] for item in items),
        Decimal("0.00")
    ))
    total = money(subtotal - discount_total + tax_total)

    max_amount = Decimal("999999999999.99")
    if any(
        value > max_amount
        for value in (
            subtotal, discount_total, tax_total, total
        )
    ):
        raise QuoteValidationError({
            "items": "quote_total_out_of_range"
        })

    # UUID para evitar colisiones por generación de folios
    # concurrentes. Más adelante se puede agregar una
    # numeración secuencial por tenant.
    quote_number = f"COT-{uuid4().hex[:24].upper()}"

    quote = Quote(
        tenant_id=tenant_id,
        quote_number=quote_number,
        status="draft",
        currency="MXN",
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=tax_total,
        total=total,
        created_by=user_id,
        **cleaned
    )

    db.session.add(quote)
    db.session.flush()

    for item_data in items:
        db.session.add(
            QuoteItem(
                tenant_id=tenant_id,
                quote_id=quote.id,
                **item_data
            )
        )

    db.session.add(
        QuoteStatusHistory(
            tenant_id=tenant_id,
            quote_id=quote.id,
            previous_status=None,
            new_status="draft",
            notes="Cotización creada",
            changed_by=user_id
        )
    )

    db.session.flush()
    quote_id = quote.id

    # La transacción se confirma en la ruta.
    return quote_id


def list_quotes(tenant_id, page=1, per_page=20):
    stmt = (
        select(Quote)
        .where(Quote.tenant_id == tenant_id)
        .order_by(Quote.id.desc())
    )

    return db.paginate(
        stmt,
        page=page,
        per_page=per_page,
        error_out=False
    )
