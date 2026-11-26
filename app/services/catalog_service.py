"""CAT-01: catálogo de productos y servicios, proveedores y partidas de servicio.

Decisiones (reversibles):
- Las categorías son globales y las administra la plataforma; cada organización
  publica sus ofertas en ellas.
- El mobiliario existente no se migra: los artículos de inventario se listan en el
  catálogo bajo «Renta de mobiliario» y conservan sus reglas de inventario.
- Una partida «bajo cotización» se guarda con importe 0 y ``price_status=pending``;
  queda fuera del total hasta registrar el importe acordado.
"""
import re
import unicodedata
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select

from app.extensions import db
from app.models.catalog import (
    FULFILLMENT_TYPES, OFFER_STATUSES, PRICING_MODES, CatalogCategory, CatalogOffer, Provider,
)
from app.models.event import Event
from app.models.identity import now
from app.models.inventory_item import InventoryItem
from app.models.quote import Quote
from app.models.quote_item import QuoteItem

INITIAL_CATEGORIES = (
    # (slug, nombre, is_inventory, requires_special_permits)
    ("renta-de-mobiliario", "Renta de mobiliario", True, False),
    ("cocteleria-y-barras-de-bebidas", "Coctelería y barras de bebidas", False, False),
    ("barras-de-postres", "Barras de postres", False, False),
    ("snacks-y-mesas-de-botanas", "Snacks y mesas de botanas", False, False),
    ("tablas-y-barras-de-quesos", "Tablas y barras de quesos", False, False),
    ("banquetes-y-catering", "Banquetes y catering", False, False),
    ("fotografia", "Fotografía", False, False),
    ("video", "Video", False, False),
    ("musica-en-vivo", "Música en vivo", False, False),
    ("dj-y-musica-grabada", "DJ y música grabada", False, False),
    ("pirotecnia-y-efectos-especiales", "Pirotecnia y espectáculos de efectos especiales", False, True),
    ("otros-servicios", "Otros servicios", False, False),
)
FURNITURE_SLUG = "renta-de-mobiliario"
PRICING_LABELS = {
    "unit": "por unidad", "per_person": "por persona", "per_hour": "por hora",
    "package": "por paquete", "per_event": "por evento", "quote": "bajo cotización",
}
# Estados de cotización que ocupan agenda del proveedor.
_ACTIVE_QUOTE_STATUSES = ("draft", "sent", "accepted")
MAX_PRICE = Decimal("999999999999.99")


class CatalogError(Exception):
    def __init__(self, code, status=400, **extra):
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


# ----------------------------------------------------------------------------
# Utilidades de validación
# ----------------------------------------------------------------------------

def _body(body):
    if not isinstance(body, dict):
        raise CatalogError("invalid_json", 400)
    return body


def _only(body, allowed):
    unknown = set(body) - set(allowed)
    if unknown:
        raise CatalogError("invalid_fields", 422, fields=sorted(unknown))


def _text(body, field, limit, *, required=False):
    value = body.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise CatalogError(f"invalid_{field}", 422)
        return None
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise CatalogError(f"invalid_{field}", 422)
    return value.strip()


def _int(body, field, *, minimum=0, maximum=1_000_000):
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CatalogError(f"invalid_{field}", 422)
    return value


def _money(value, field):
    if value is None:
        return None
    if isinstance(value, bool):
        raise CatalogError(f"invalid_{field}", 422)
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CatalogError(f"invalid_{field}", 422)
    if not amount.is_finite() or amount < 0 or amount > MAX_PRICE or amount != amount.quantize(Decimal("0.01")):
        raise CatalogError(f"invalid_{field}", 422)
    return amount


def _slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:120] or "categoria"


# ----------------------------------------------------------------------------
# Categorías
# ----------------------------------------------------------------------------

def seed_categories():
    """Siembra idempotente de las categorías iniciales."""
    created = 0
    for order, (slug, name, is_inventory, special) in enumerate(INITIAL_CATEGORIES, start=1):
        if db.session.scalar(select(CatalogCategory.id).where(CatalogCategory.slug == slug)) is None:
            db.session.add(CatalogCategory(slug=slug, name=name, sort_order=order * 10, is_active=True,
                                           is_inventory=is_inventory, requires_special_permits=special))
            created += 1
    db.session.commit()
    return created


def category_dict(c):
    return {
        "id": c.id, "parent_id": c.parent_id, "name": c.name, "slug": c.slug, "description": c.description,
        "sort_order": c.sort_order, "is_active": c.is_active, "is_inventory": c.is_inventory,
        "requires_special_permits": c.requires_special_permits,
    }


def list_categories(include_inactive=False):
    query = select(CatalogCategory).order_by(CatalogCategory.sort_order, CatalogCategory.name)
    if not include_inactive:
        query = query.where(CatalogCategory.is_active.is_(True))
    return [category_dict(c) for c in db.session.scalars(query).all()]


def _category(category_id, *, active_only=True):
    if isinstance(category_id, bool) or not isinstance(category_id, int) or category_id <= 0:
        raise CatalogError("invalid_category_id", 422)
    category = db.session.get(CatalogCategory, category_id)
    if category is None or (active_only and not category.is_active):
        raise CatalogError("category_not_found", 404)
    return category


def _root(category):
    seen = set()
    while category.parent_id is not None and category.id not in seen:
        seen.add(category.id)
        category = db.session.get(CatalogCategory, category.parent_id)
    return category


def _effective_flags(category):
    """Las subcategorías heredan las banderas de su categoría raíz."""
    root = _root(category)
    return (category.is_inventory or root.is_inventory,
            category.requires_special_permits or root.requires_special_permits)


def create_category(actor_id, body):
    body = _body(body)
    _only(body, {"name", "parent_id", "description", "sort_order", "requires_special_permits"})
    name = _text(body, "name", 120, required=True)
    parent_id = body.get("parent_id")
    parent = _category(parent_id, active_only=False) if parent_id is not None else None
    if parent is not None and parent.parent_id is not None:
        raise CatalogError("max_depth_two_levels", 422)
    base = _slugify(f"{parent.slug}-{name}" if parent else name)
    slug, n = base, 2
    while db.session.scalar(select(CatalogCategory.id).where(CatalogCategory.slug == slug)) is not None:
        slug, n = f"{base}-{n}", n + 1
    special = body.get("requires_special_permits", False)
    if not isinstance(special, bool):
        raise CatalogError("invalid_requires_special_permits", 422)
    category = CatalogCategory(
        parent_id=parent.id if parent else None, name=name, slug=slug,
        description=_text(body, "description", 500), sort_order=_int(body, "sort_order", maximum=100000) or 0,
        is_active=True, is_inventory=False, requires_special_permits=special)
    db.session.add(category)
    db.session.flush()
    from app.services.platform_service import record_audit
    record_audit(actor_id, "catalog_category.create", target_type="catalog_category", target_id=category.id,
                 details={"name": name, "parent_id": category.parent_id})
    db.session.commit()
    return category


def update_category(actor_id, category_id, body):
    body = _body(body)
    _only(body, {"name", "description", "sort_order", "is_active", "requires_special_permits"})
    category = _category(category_id, active_only=False)
    changes = {}
    if "name" in body:
        changes["name"] = _text(body, "name", 120, required=True)
    if "description" in body:
        changes["description"] = _text(body, "description", 500)
    if "sort_order" in body:
        changes["sort_order"] = _int(body, "sort_order", maximum=100000) or 0
    for flag in ("is_active", "requires_special_permits"):
        if flag in body:
            if not isinstance(body[flag], bool):
                raise CatalogError(f"invalid_{flag}", 422)
            changes[flag] = body[flag]
    if changes.get("is_active") is False and category.slug == FURNITURE_SLUG:
        raise CatalogError("furniture_category_required", 409)
    for key, value in changes.items():
        setattr(category, key, value)
    from app.services.platform_service import record_audit
    record_audit(actor_id, "catalog_category.update", target_type="catalog_category", target_id=category.id,
                 details={k: v for k, v in changes.items()})
    db.session.commit()
    return category


# ----------------------------------------------------------------------------
# Proveedores (por organización)
# ----------------------------------------------------------------------------

def provider_dict(p):
    return {"id": p.id, "name": p.name, "contact_name": p.contact_name, "contact_email": p.contact_email,
            "phone": p.phone, "notes": p.notes, "status": p.status}


def list_providers(tenant_id):
    rows = db.session.scalars(select(Provider).where(Provider.tenant_id == tenant_id)
                              .order_by(Provider.name)).all()
    return [provider_dict(p) for p in rows]


def _provider(tenant_id, provider_id, *, active_only=False):
    if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0:
        raise CatalogError("invalid_provider_id", 422)
    provider = db.session.scalar(select(Provider).where(Provider.id == provider_id, Provider.tenant_id == tenant_id))
    if provider is None or (active_only and provider.status != "active"):
        raise CatalogError("provider_not_found", 404)
    return provider


def save_provider(tenant_id, body, provider_id=None):
    body = _body(body)
    _only(body, {"name", "contact_name", "contact_email", "phone", "notes", "status"})
    provider = _provider(tenant_id, provider_id) if provider_id is not None else Provider(tenant_id=tenant_id)
    if provider_id is None or "name" in body:
        provider.name = _text(body, "name", 180, required=True)
    for field, limit in (("contact_name", 180), ("contact_email", 254), ("phone", 40), ("notes", 1000)):
        if field in body:
            setattr(provider, field, _text(body, field, limit))
    if provider.contact_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", provider.contact_email):
        raise CatalogError("invalid_contact_email", 422)
    if "status" in body:
        if body["status"] not in ("active", "inactive"):
            raise CatalogError("invalid_status", 422)
        provider.status = body["status"]
    duplicate = db.session.scalar(select(Provider.id).where(
        Provider.tenant_id == tenant_id, Provider.name == provider.name,
        Provider.id != (provider.id or 0)))
    if duplicate is not None:
        raise CatalogError("provider_name_taken", 409)
    db.session.add(provider)
    db.session.commit()
    return provider


# ----------------------------------------------------------------------------
# Ofertas
# ----------------------------------------------------------------------------

def offer_dict(o, *, categories=None, providers=None):
    categories = categories or {}
    providers = providers or {}
    category = categories.get(o.category_id)
    provider = providers.get(o.provider_id)
    return {
        "kind": "offer", "id": o.id, "name": o.name, "description": o.description, "status": o.status,
        "category_id": o.category_id, "category_name": category.name if category else None,
        "provider_id": o.provider_id, "provider_name": provider.name if provider else None,
        "pricing_mode": o.pricing_mode, "pricing_label": PRICING_LABELS.get(o.pricing_mode),
        "unit_price": str(o.unit_price) if o.unit_price is not None else None,
        "price_pending": o.pricing_mode == "quote",
        "fulfillment_type": o.fulfillment_type, "inventory_item_id": o.inventory_item_id,
        "duration_hours": str(o.duration_hours) if o.duration_hours is not None else None,
        "min_guests": o.min_guests, "max_guests": o.max_guests, "coverage": o.coverage,
        "min_notice_days": o.min_notice_days, "setup_requirements": o.setup_requirements,
        "daily_capacity": o.daily_capacity, "requires_provider_confirmation": o.requires_provider_confirmation,
        "venue_restrictions": o.venue_restrictions, "required_documents": o.required_documents,
        "requires_special_permits": bool(category and _effective_flags(category)[1]),
        "shared": bool(o.shared),
    }


def _lookup_maps(tenant_id, offers):
    categories = {c.id: c for c in db.session.scalars(select(CatalogCategory)).all()}
    provider_ids = {o.provider_id for o in offers if o.provider_id}
    providers = {p.id: p for p in db.session.scalars(select(Provider).where(
        Provider.tenant_id == tenant_id, Provider.id.in_(provider_ids))).all()} if provider_ids else {}
    return categories, providers


def save_offer(tenant_id, actor_id, body, offer_id=None):
    body = _body(body)
    _only(body, {
        "name", "description", "category_id", "provider_id", "status", "pricing_mode", "unit_price",
        "fulfillment_type", "inventory_item_id", "duration_hours", "min_guests", "max_guests", "coverage",
        "min_notice_days", "setup_requirements", "daily_capacity", "requires_provider_confirmation",
        "venue_restrictions", "required_documents", "shared",
    })
    if offer_id is not None:
        offer = db.session.scalar(select(CatalogOffer).where(
            CatalogOffer.id == offer_id, CatalogOffer.tenant_id == tenant_id).with_for_update())
        if offer is None:
            raise CatalogError("offer_not_found", 404)
    else:
        offer = CatalogOffer(tenant_id=tenant_id, created_by=actor_id, status="draft")
    creating = offer_id is None

    def has(field):
        return creating or field in body

    if has("name"):
        offer.name = _text(body, "name", 180, required=True)
    if has("description"):
        offer.description = _text(body, "description", 5000)
    if has("category_id"):
        offer.category_id = _category(body.get("category_id")).id
    if "provider_id" in body:
        offer.provider_id = (_provider(tenant_id, body["provider_id"], active_only=True).id
                             if body["provider_id"] is not None else None)
    if "status" in body:
        if body["status"] not in OFFER_STATUSES:
            raise CatalogError("invalid_status", 422)
        offer.status = body["status"]
    if has("pricing_mode"):
        if body.get("pricing_mode") not in PRICING_MODES:
            raise CatalogError("invalid_pricing_mode", 422)
        offer.pricing_mode = body["pricing_mode"]
    if has("unit_price"):
        offer.unit_price = _money(body.get("unit_price"), "unit_price")
    if has("fulfillment_type"):
        if body.get("fulfillment_type") not in FULFILLMENT_TYPES:
            raise CatalogError("invalid_fulfillment_type", 422)
        offer.fulfillment_type = body["fulfillment_type"]
    if "inventory_item_id" in body or creating:
        item_id = body.get("inventory_item_id")
        if item_id is not None:
            if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
                raise CatalogError("invalid_inventory_item_id", 422)
            if db.session.scalar(select(InventoryItem.id).where(
                    InventoryItem.id == item_id, InventoryItem.tenant_id == tenant_id)) is None:
                raise CatalogError("inventory_item_not_found", 404)
        offer.inventory_item_id = item_id
    for field, limit in (("coverage", 255), ("setup_requirements", 1000),
                         ("venue_restrictions", 1000), ("required_documents", 1000)):
        if field in body:
            setattr(offer, field, _text(body, field, limit))
    for field, maximum in (("min_guests", 100000), ("max_guests", 100000), ("min_notice_days", 3650),
                           ("daily_capacity", 1000)):
        if field in body:
            setattr(offer, field, _int(body, field, minimum=0 if field == "min_notice_days" else 1, maximum=maximum))
    if "duration_hours" in body:
        hours = _money(body["duration_hours"], "duration_hours")
        if hours is not None and not Decimal("0.25") <= hours <= Decimal("240"):
            raise CatalogError("invalid_duration_hours", 422)
        offer.duration_hours = hours
    if "shared" in body:
        if not isinstance(body["shared"], bool):
            raise CatalogError("invalid_shared", 422)
        offer.shared = body["shared"]
    if "requires_provider_confirmation" in body:
        if not isinstance(body["requires_provider_confirmation"], bool):
            raise CatalogError("invalid_requires_provider_confirmation", 422)
        offer.requires_provider_confirmation = body["requires_provider_confirmation"]

    # Reglas de consistencia.
    if offer.pricing_mode == "quote":
        offer.unit_price = None
    elif offer.unit_price is None:
        raise CatalogError("unit_price_required", 422)
    if offer.fulfillment_type == "inventory":
        if offer.inventory_item_id is None:
            raise CatalogError("inventory_item_required", 422)
    elif offer.inventory_item_id is not None:
        raise CatalogError("inventory_item_only_for_inventory", 422)
    if offer.min_guests and offer.max_guests and offer.min_guests > offer.max_guests:
        raise CatalogError("invalid_guest_range", 422)
    category = db.session.get(CatalogCategory, offer.category_id)
    is_inventory, special = _effective_flags(category)
    if special:
        # Pirotecnia y efectos: siempre con confirmación del proveedor.
        offer.requires_provider_confirmation = True
    db.session.add(offer)
    db.session.commit()
    return offer


def list_catalog(tenant_id, *, category_id=None, search=None, status=None, include_inventory=True,
                 published_only=False, page=1, per_page=50):
    """Ofertas de la organización más su mobiliario (artículos de inventario activos)."""
    categories = {c.id: c for c in db.session.scalars(select(CatalogCategory)).all()}
    wanted = None
    if category_id is not None:
        wanted = {cid for cid, c in categories.items() if cid == category_id or c.parent_id == category_id}
    query = select(CatalogOffer).where(CatalogOffer.tenant_id == tenant_id).order_by(CatalogOffer.name)
    if wanted is not None:
        query = query.where(CatalogOffer.category_id.in_(wanted))
    if published_only:
        query = query.where(CatalogOffer.status == "published")
    elif status in OFFER_STATUSES:
        query = query.where(CatalogOffer.status == status)
    else:
        query = query.where(CatalogOffer.status != "archived")
    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(CatalogOffer.name.like(like), CatalogOffer.description.like(like)))
    offers = db.session.scalars(query.limit(500)).all()
    _, providers = _lookup_maps(tenant_id, offers)
    items = [offer_dict(o, categories=categories, providers=providers) for o in offers]

    furniture = next((c for c in categories.values() if c.slug == FURNITURE_SLUG), None)
    furniture_wanted = furniture is not None and (wanted is None or furniture.id in wanted)
    if include_inventory and furniture_wanted and status in (None, "", "published"):
        inv_query = select(InventoryItem).where(InventoryItem.tenant_id == tenant_id,
                                                InventoryItem.is_active.is_(True)).order_by(InventoryItem.name)
        if search:
            like = f"%{search.strip()}%"
            inv_query = inv_query.where(or_(InventoryItem.name.like(like), InventoryItem.sku.like(like)))
        for item in db.session.scalars(inv_query.limit(500)).all():
            items.append({
                "kind": "inventory", "id": item.id, "name": item.name, "description": item.description,
                "status": "published", "category_id": furniture.id, "category_name": furniture.name,
                "provider_id": None, "provider_name": None, "pricing_mode": "unit",
                "pricing_label": f"por {item.unit}" if item.unit else PRICING_LABELS["unit"],
                "unit_price": str(item.rental_price) if item.rental_price is not None else None,
                "price_pending": item.rental_price is None, "fulfillment_type": "inventory",
                "inventory_item_id": item.id, "unit": item.unit, "sku": item.sku,
                "requires_special_permits": False,
            })
    total = len(items)
    start = (page - 1) * per_page
    return total, items[start:start + per_page]


# ----------------------------------------------------------------------------
# Partidas de servicio en cotizaciones
# ----------------------------------------------------------------------------

def _local_day_bounds(tenant_id, event_id):
    """Día local del evento (zona horaria de la empresa) como rango UTC.

    Las fechas se guardan en UTC sin zona; un evento a las 18:00 en México cae al
    día siguiente en UTC, así que la capacidad diaria se cuenta por día local.
    """
    from zoneinfo import ZoneInfo
    from datetime import datetime, timezone
    from app.models import Tenant
    event = db.session.scalar(select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id))
    if event is None or event.starts_at is None:
        return None
    tz_name = db.session.scalar(select(Tenant.timezone).where(Tenant.id == tenant_id)) or "America/Mexico_City"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Mexico_City")
    local = event.starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
    start_local = datetime(local.year, local.month, local.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)
    return to_utc(start_local), to_utc(end_local)


def offer_availability(tenant_id, offer, event_id, *, exclude_quote_id=None):
    """Disponibilidad de agenda. Sin capacidad diaria registrada no se puede
    comprobar automáticamente: queda pendiente de confirmación."""
    if offer.fulfillment_type == "inventory":
        return "not_required"
    if offer.fulfillment_type == "manual" or offer.daily_capacity is None or offer.requires_provider_confirmation:
        return "pending_confirmation"
    bounds = _local_day_bounds(tenant_id, event_id)
    if bounds is None:
        return "pending_confirmation"
    start, end = bounds
    query = (select(func.count(func.distinct(Quote.event_id)))
             .select_from(QuoteItem)
             .join(Quote, (Quote.id == QuoteItem.quote_id) & (Quote.tenant_id == QuoteItem.tenant_id))
             .join(Event, (Event.id == Quote.event_id) & (Event.tenant_id == Quote.tenant_id))
             .where(QuoteItem.tenant_id == tenant_id, QuoteItem.offer_id == offer.id,
                    QuoteItem.fulfillment_status.in_(("available", "confirmed", "pending_confirmation")),
                    Quote.status.in_(_ACTIVE_QUOTE_STATUSES), Quote.event_id != event_id,
                    Event.starts_at >= start, Event.starts_at < end))
    if exclude_quote_id is not None:
        query = query.where(Quote.id != exclude_quote_id)
    used = db.session.scalar(query) or 0
    return "available" if used < offer.daily_capacity else "unavailable"


def build_offer_item(tenant_id, offer_id, event_id, item, index):
    """Completa una partida de cotización a partir de una oferta del catálogo."""
    if isinstance(offer_id, bool) or not isinstance(offer_id, int) or offer_id <= 0:
        raise CatalogError(f"items[{index}].offer_id", 422)
    offer = db.session.scalar(select(CatalogOffer).where(
        CatalogOffer.id == offer_id, CatalogOffer.tenant_id == tenant_id))
    if offer is None or offer.status != "published":
        raise CatalogError("offer_not_found", 404, item=index)
    category = db.session.get(CatalogCategory, offer.category_id)
    _, special = _effective_flags(category)
    pending = offer.pricing_mode == "quote"
    details = {}
    for field in ("guests", "hours"):
        value = item.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise CatalogError(f"items[{index}].{field}", 422)
            details[field] = str(value)
    note = item.get("service_notes")
    if note is not None:
        if not isinstance(note, str) or len(note) > 1000:
            raise CatalogError(f"items[{index}].service_notes", 422)
        details["notes"] = note.strip()
    if offer.venue_restrictions:
        details["venue_restrictions"] = offer.venue_restrictions
    if offer.required_documents:
        details["required_documents"] = offer.required_documents
    return {
        "item_type": "inventory" if offer.fulfillment_type == "inventory" else "service",
        "inventory_item_id": offer.inventory_item_id if offer.fulfillment_type == "inventory" else None,
        "offer_id": offer.id, "provider_id": offer.provider_id, "category_id": offer.category_id,
        "pricing_mode": offer.pricing_mode, "price_status": "pending" if pending else "confirmed",
        "fulfillment_status": offer_availability(tenant_id, offer, event_id),
        "compliance_status": "pending" if (special or offer.venue_restrictions or offer.required_documents)
        else "not_required",
        "service_details": details or None,
        "default_description": offer.name,
        "default_unit_price": offer.unit_price,
    }


ITEM_BLOCKING = {
    "price_pending": lambda i: i.price_status == "pending",
    "cost_pending": lambda i: getattr(i, "cost_status", None) == "pending",
    "confirmation_pending": lambda i: i.fulfillment_status in ("pending_confirmation", "unavailable"),
    "compliance_pending": lambda i: i.compliance_status == "pending",
}


def pending_summary(items):
    summary = {key: sum(1 for i in items if check(i)) for key, check in ITEM_BLOCKING.items()}
    summary["blocking"] = sum(1 for i in items if any(check(i) for check in ITEM_BLOCKING.values()))
    return summary



# ----------------------------------------------------------------------------
# NET-01: catálogo compartido entre organizaciones
# ----------------------------------------------------------------------------

def _network_offers_query():
    from app.models import Tenant
    return (select(CatalogOffer, Tenant)
            .join(Tenant, Tenant.id == CatalogOffer.tenant_id)
            .where(CatalogOffer.shared.is_(True), CatalogOffer.status == "published",
                   Tenant.status == "active"))


def network_offer_dict(offer, tenant, categories):
    data = offer_dict(offer, categories=categories)
    # Proveedor = la organización que comparte; sus proveedores internos no se exponen.
    data.update(kind="network", provider_id=None, provider_name=None, supplier_tenant_id=tenant.id,
                supplier_name=tenant.name, inventory_item_id=None, daily_capacity=None,
                # El precio publicado es el costo para quien cotiza.
                cost_unit_price=data["unit_price"])
    return data


def list_network(tenant_id, *, category_id=None, search=None, page=1, per_page=50):
    """Ofertas compartidas y publicadas de las demás organizaciones activas."""
    categories = {c.id: c for c in db.session.scalars(select(CatalogCategory)).all()}
    query = _network_offers_query().where(CatalogOffer.tenant_id != tenant_id).order_by(CatalogOffer.name)
    if category_id is not None:
        wanted = {cid for cid, c in categories.items() if cid == category_id or c.parent_id == category_id}
        query = query.where(CatalogOffer.category_id.in_(wanted))
    if search:
        like = f"%{search.strip()}%"
        from app.models import Tenant
        query = query.where(or_(CatalogOffer.name.like(like), CatalogOffer.description.like(like),
                                Tenant.name.like(like)))
    rows = db.session.execute(query.limit(500)).all()
    items = [network_offer_dict(o, t, categories) for o, t in rows]
    start = (page - 1) * per_page
    return len(items), items[start:start + per_page]


def build_network_item(tenant_id, network_offer_id, item, index):
    """Partida que presta otra organización. Siempre requiere su confirmación."""
    if isinstance(network_offer_id, bool) or not isinstance(network_offer_id, int) or network_offer_id <= 0:
        raise CatalogError("invalid_network_offer_id", 422)
    row = db.session.execute(_network_offers_query().where(CatalogOffer.id == network_offer_id)).first()
    if row is None or row[0].tenant_id == tenant_id:
        raise CatalogError("network_offer_not_found", 404, item=index)
    offer, supplier = row
    category = db.session.get(CatalogCategory, offer.category_id)
    _, special = _effective_flags(category)
    cost_pending = offer.pricing_mode == "quote"
    details = {}
    for field in ("guests", "hours"):
        value = item.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise CatalogError(f"items[{index}].{field}", 422)
            details[field] = str(value)
    note = item.get("service_notes")
    if note is not None:
        if not isinstance(note, str) or len(note) > 1000:
            raise CatalogError(f"items[{index}].service_notes", 422)
        details["notes"] = note.strip()
    if offer.venue_restrictions:
        details["venue_restrictions"] = offer.venue_restrictions
    if offer.required_documents:
        details["required_documents"] = offer.required_documents
    return {
        "item_type": "service", "inventory_item_id": None,
        "offer_id": None, "provider_id": None, "category_id": offer.category_id,
        "pricing_mode": offer.pricing_mode,
        "supplier_tenant_id": supplier.id, "network_offer_id": offer.id,
        "cost_unit_price": None if cost_pending else offer.unit_price,
        "cost_status": "pending" if cost_pending else "confirmed",
        # La fecha la confirma la organización proveedora.
        "fulfillment_status": "pending_confirmation",
        "compliance_status": "pending" if (special or offer.venue_restrictions or offer.required_documents)
        else "not_required",
        "service_details": details or None,
        "default_description": offer.name,
        "default_unit_price": offer.unit_price,
        "supplier_name": supplier.name,
    }
