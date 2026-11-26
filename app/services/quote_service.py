
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


PRICE_STATUS_LABELS = {"confirmed": "Precio confirmado", "pending": "Precio pendiente"}


def serialize_item(item, names=None):
    names = names or {}
    return {
        "offer_id": item.offer_id,
        "provider_id": item.provider_id,
        "provider_name": names.get(("provider", item.provider_id)),
        "category_id": item.category_id,
        "category_name": names.get(("category", item.category_id)),
        "pricing_mode": item.pricing_mode,
        "price_status": item.price_status,
        "fulfillment_status": item.fulfillment_status,
        "compliance_status": item.compliance_status,
        "service_details": item.service_details,
        # NET-01: partida de otra organización (costo del proveedor y margen).
        "supplier_tenant_id": item.supplier_tenant_id,
        "supplier_name": names.get(("tenant", item.supplier_tenant_id)),
        "network_offer_id": item.network_offer_id,
        "cost_unit_price": str(item.cost_unit_price) if item.cost_unit_price is not None else None,
        "cost_status": item.cost_status,
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
        names = _item_names(quote.tenant_id, quote.items)
        result["items"] = [
            serialize_item(item, names)
            for item in sorted(
                quote.items,
                key=lambda row: (row.sort_order, row.id)
            )
        ]
        from app.services.catalog_service import pending_summary
        summary = pending_summary(quote.items)
        # «total» solo suma partidas con precio confirmado.
        result["confirmed_total"] = str(quote.total)
        result["pending"] = summary

    return result


def _item_names(tenant_id, items):
    from app.models.catalog import CatalogCategory, Provider
    names = {}
    provider_ids = {i.provider_id for i in items if i.provider_id}
    category_ids = {i.category_id for i in items if i.category_id}
    if provider_ids:
        for p in db.session.scalars(select(Provider).where(
                Provider.tenant_id == tenant_id, Provider.id.in_(provider_ids))).all():
            names[("provider", p.id)] = p.name
    if category_ids:
        for c in db.session.scalars(select(CatalogCategory).where(
                CatalogCategory.id.in_(category_ids))).all():
            names[("category", c.id)] = c.name
    supplier_ids = {i.supplier_tenant_id for i in items if getattr(i, "supplier_tenant_id", None)}
    if supplier_ids:
        from app.models import Tenant
        for t in db.session.scalars(select(Tenant).where(Tenant.id.in_(supplier_ids))).all():
            names[("tenant", t.id)] = t.name
    return names


def recalculate_totals(quote):
    """Recalcula los totales del encabezado a partir de las partidas."""
    zero = Decimal("0.00")
    quote.subtotal = money(sum((i.subtotal for i in quote.items), zero))
    quote.discount_total = money(sum((i.discount_amount for i in quote.items), zero))
    quote.tax_total = money(sum((i.tax_amount for i in quote.items), zero))
    quote.total = money(quote.subtotal - quote.discount_total + quote.tax_total)


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

    # NET-01: queda registro de qué organización recibe datos del evento y del cliente.
    suppliers = {}
    for item_data in items:
        if item_data.get("supplier_tenant_id"):
            suppliers.setdefault(item_data["supplier_tenant_id"], []).append(item_data["network_offer_id"])
    if suppliers:
        from app.services.platform_service import record_audit
        for supplier_id, offer_ids in suppliers.items():
            record_audit(user_id, "network_request.create", tenant_id=tenant_id, target_type="quote",
                         target_id=quote_id, details={"supplier_tenant_id": supplier_id,
                                                      "network_offer_ids": offer_ids,
                                                      "shared_data": ["event", "client"]})

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

from datetime import datetime, timezone


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

    if new_status == "accepted":
        # CAT-01: no se cierra la contratación con precios, confirmaciones o
        # documentos pendientes (p. ej. pirotecnia sin confirmación del proveedor).
        from app.services.catalog_service import pending_summary
        summary = pending_summary(quote.items)
        if summary["blocking"]:
            raise QuoteValidationError(
                {"items": "pending_items", "pending": summary},
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

# ----------------------------------------------------------------------------
# CAT-01: seguimiento de partidas (precio acordado, confirmación y documentos)
# ----------------------------------------------------------------------------

EDITABLE_QUOTE_STATUSES = ("draft", "sent")
FULFILLMENT_UPDATES = ("pending_confirmation", "confirmed", "unavailable")
COMPLIANCE_UPDATES = ("pending", "approved")


def update_quote_item(tenant_id, quote_id, item_id, user_id, data, *, provider_id=None, _as_supplier=False):
    """Registra el importe acordado, la confirmación del proveedor o la revisión
    de restricciones/documentos de una partida.

    ``provider_id`` limita la operación a las partidas de ese proveedor (portal
    de proveedores); en ese caso la revisión documental no se puede aprobar.
    """
    from app.services.quote_calculator import QuoteCalculationError, calculate_item

    if not isinstance(data, dict):
        raise QuoteValidationError({"body": "invalid_json"})
    allowed = {"unit_price", "fulfillment_status", "compliance_status", "notes"}
    unknown = set(data) - allowed
    if unknown or not data:
        raise QuoteValidationError({"fields": sorted(unknown) or "required"}, 422)

    quote = db.session.scalar(select(Quote).where(
        Quote.id == quote_id, Quote.tenant_id == tenant_id).with_for_update())
    if quote is None:
        raise QuoteValidationError({"quote": "not_found"}, 404)
    item = next((i for i in quote.items if i.id == item_id), None)
    if item is None or (provider_id is not None and item.provider_id != provider_id):
        raise QuoteValidationError({"item": "not_found"}, 404)
    if quote.status not in EDITABLE_QUOTE_STATUSES:
        raise QuoteValidationError({"quote": "not_editable", "status": quote.status}, 409)

    changes = {}
    if "unit_price" in data:
        try:
            calculated = calculate_item({
                "quantity": item.quantity, "unit_price": data["unit_price"],
                "discount_amount": "0", "tax_rate": item.tax_rate,
            })
        except (QuoteCalculationError, ArithmeticError) as exc:
            raise QuoteValidationError({"unit_price": str(exc)}, 422) from exc
        if calculated["unit_price"] != Decimal(str(data["unit_price"])):
            raise QuoteValidationError({"unit_price": "maximum_two_decimals"}, 422)
        if calculated["total"] > Decimal("999999999999.99"):
            raise QuoteValidationError({"unit_price": "amount_out_of_range"}, 422)
        for field in ("unit_price", "subtotal", "tax_amount", "total"):
            setattr(item, field, calculated[field])
        item.discount_amount = Decimal("0.00")
        item.price_status = "confirmed"
        changes["unit_price"] = str(calculated["unit_price"])
    if "fulfillment_status" in data:
        if item.supplier_tenant_id is not None and provider_id is None and not _as_supplier:
            # NET-01: la fecha la confirma la organización que presta el servicio.
            raise QuoteValidationError({"fulfillment_status": "supplier_only"}, 403)
        if item.fulfillment_status == "not_required" or data["fulfillment_status"] not in FULFILLMENT_UPDATES:
            raise QuoteValidationError({"fulfillment_status": "invalid_status"}, 422)
        item.fulfillment_status = data["fulfillment_status"]
        changes["fulfillment_status"] = item.fulfillment_status
    if "compliance_status" in data:
        if provider_id is not None:
            raise QuoteValidationError({"compliance_status": "organization_only"}, 403)
        if item.compliance_status == "not_required" or data["compliance_status"] not in COMPLIANCE_UPDATES:
            raise QuoteValidationError({"compliance_status": "invalid_status"}, 422)
        item.compliance_status = data["compliance_status"]
        changes["compliance_status"] = item.compliance_status
    notes = data.get("notes")
    if notes is not None and (not isinstance(notes, str) or len(notes) > 1000):
        raise QuoteValidationError({"notes": "invalid_notes"}, 422)

    recalculate_totals(quote)
    db.session.add(QuoteStatusHistory(
        tenant_id=tenant_id, quote_id=quote.id, previous_status=quote.status, new_status=quote.status,
        changed_by=user_id,
        notes=(f"Partida {item.id} ({item.description[:120]}): "
               + ", ".join(f"{k}={v}" for k, v in changes.items())
               + (f". {notes.strip()}" if notes and notes.strip() else ""))[:2000],
    ))
    db.session.flush()
    return quote, item


def provider_items(tenant_id, provider_id, *, page=1, per_page=50):
    """Partidas asignadas a un proveedor, con el mínimo contexto del evento."""
    from app.models.event import Event
    query = (select(QuoteItem, Quote, Event)
             .join(Quote, (Quote.id == QuoteItem.quote_id) & (Quote.tenant_id == QuoteItem.tenant_id))
             .join(Event, (Event.id == Quote.event_id) & (Event.tenant_id == Quote.tenant_id))
             .where(QuoteItem.tenant_id == tenant_id, QuoteItem.provider_id == provider_id)
             .order_by(Event.starts_at.desc(), QuoteItem.id))
    rows = db.session.execute(query.limit(per_page).offset((page - 1) * per_page)).all()
    names = _item_names(tenant_id, [r[0] for r in rows])
    return [{
        **serialize_item(item, names),
        "quote_id": quote.id, "quote_number": quote.quote_number, "quote_status": quote.status,
        "event_name": event.name,
        # Igual que la API de eventos: UTC explícito.
        "event_starts_at": event.starts_at.isoformat() + "Z" if event.starts_at else None,
        "event_location": event.location, "estimated_guests": event.estimated_guests,
    } for item, quote, event in rows]



# ----------------------------------------------------------------------------
# NET-01: solicitudes recibidas por la organización proveedora
# ----------------------------------------------------------------------------

def _request_dict(item, quote, event, client, requester, names):
    cost_total = (money(item.cost_unit_price * item.quantity)
                  if item.cost_unit_price is not None else None)
    return {
        "id": item.id, "description": item.description, "quantity": str(item.quantity),
        "pricing_mode": item.pricing_mode, "category_name": names.get(("category", item.category_id)),
        "network_offer_id": item.network_offer_id,
        "cost_unit_price": str(item.cost_unit_price) if item.cost_unit_price is not None else None,
        "cost_total": str(cost_total) if cost_total is not None else None,
        "cost_status": item.cost_status, "fulfillment_status": item.fulfillment_status,
        "compliance_status": item.compliance_status, "service_details": item.service_details,
        "quote_number": quote.quote_number, "quote_status": quote.status,
        "requester_tenant_id": requester.id, "requester_name": requester.name,
        "event_name": event.name,
        "event_starts_at": event.starts_at.isoformat() + "Z" if event.starts_at else None,
        "event_ends_at": event.ends_at.isoformat() + "Z" if event.ends_at else None,
        "event_location": event.location, "estimated_guests": event.estimated_guests,
        # Decisión del negocio: la organización proveedora ve también al cliente final.
        "client": {
            "name": " ".join(p for p in (client.first_name, client.last_name) if p) or None,
            "business_name": client.business_name, "email": client.email, "phone": client.phone,
            "whatsapp": client.whatsapp,
        },
    }


def _network_rows(supplier_tenant_id, item_id=None):
    from app.models import Tenant
    from app.models.crm import Client
    from app.models.event import Event
    query = (select(QuoteItem, Quote, Event, Client, Tenant)
             .join(Quote, (Quote.id == QuoteItem.quote_id) & (Quote.tenant_id == QuoteItem.tenant_id))
             .join(Event, (Event.id == Quote.event_id) & (Event.tenant_id == Quote.tenant_id))
             .join(Client, (Client.id == Quote.client_id) & (Client.tenant_id == Quote.tenant_id))
             .join(Tenant, Tenant.id == Quote.tenant_id)
             .where(QuoteItem.supplier_tenant_id == supplier_tenant_id)
             .order_by(Event.starts_at.desc(), QuoteItem.id))
    if item_id is not None:
        query = query.where(QuoteItem.id == item_id)
    return db.session.execute(query.limit(200)).all()


def network_requests(supplier_tenant_id):
    rows = _network_rows(supplier_tenant_id)
    names = _item_names(None, [r[0] for r in rows])
    return [_request_dict(*row, names) for row in rows]


def update_network_request(supplier_tenant_id, item_id, user_id, data):
    """La organización proveedora registra su costo y confirma (o rechaza) la fecha."""
    if not isinstance(data, dict):
        raise QuoteValidationError({"body": "invalid_json"})
    unknown = set(data) - {"cost_unit_price", "fulfillment_status", "notes"}
    if unknown or not data:
        raise QuoteValidationError({"fields": sorted(unknown) or "required"}, 422)
    row = db.session.execute(select(QuoteItem.tenant_id, QuoteItem.quote_id).where(
        QuoteItem.id == item_id, QuoteItem.supplier_tenant_id == supplier_tenant_id)).first()
    if row is None:
        raise QuoteValidationError({"item": "not_found"}, 404)
    requester_id, quote_id = row
    quote = db.session.scalar(select(Quote).where(
        Quote.id == quote_id, Quote.tenant_id == requester_id).with_for_update())
    item = next(i for i in quote.items if i.id == item_id)
    if quote.status not in EDITABLE_QUOTE_STATUSES:
        raise QuoteValidationError({"quote": "not_editable", "status": quote.status}, 409)
    changes = {}
    if "cost_unit_price" in data:
        raw = data["cost_unit_price"]
        try:
            cost = Decimal(str(raw))
        except Exception:
            raise QuoteValidationError({"cost_unit_price": "invalid_amount"}, 422)
        if isinstance(raw, bool) or not cost.is_finite() or cost < 0 or cost != cost.quantize(Decimal("0.01")) \
                or cost > Decimal("999999999999.99"):
            raise QuoteValidationError({"cost_unit_price": "invalid_amount"}, 422)
        item.cost_unit_price, item.cost_status = cost, "confirmed"
        changes["cost_unit_price"] = str(cost)
    if "fulfillment_status" in data:
        if data["fulfillment_status"] not in FULFILLMENT_UPDATES:
            raise QuoteValidationError({"fulfillment_status": "invalid_status"}, 422)
        item.fulfillment_status = data["fulfillment_status"]
        changes["fulfillment_status"] = item.fulfillment_status
    notes = data.get("notes")
    if notes is not None and (not isinstance(notes, str) or len(notes) > 1000):
        raise QuoteValidationError({"notes": "invalid_notes"}, 422)
    db.session.add(QuoteStatusHistory(
        tenant_id=requester_id, quote_id=quote.id, previous_status=quote.status, new_status=quote.status,
        changed_by=user_id,
        notes=(f"Proveedor de la red, partida {item.id}: "
               + ", ".join(f"{k}={v}" for k, v in changes.items())
               + (f". {notes.strip()}" if notes and notes.strip() else ""))[:2000],
    ))
    from app.services.platform_service import record_audit
    record_audit(user_id, "network_request.respond", tenant_id=supplier_tenant_id, target_type="quote_item",
                 target_id=item.id, details={"requester_tenant_id": requester_id, **changes})
    db.session.flush()
    return network_requests_item(supplier_tenant_id, item_id)


def network_requests_item(supplier_tenant_id, item_id):
    rows = _network_rows(supplier_tenant_id, item_id)
    names = _item_names(None, [r[0] for r in rows])
    return _request_dict(*rows[0], names) if rows else None
