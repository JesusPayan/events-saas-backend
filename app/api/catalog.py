"""CAT-01: catálogo de la organización, proveedores y portal de proveedores."""
from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from app.extensions import db
from app.models.quote_item import QuoteItem
from app.security import tenant_permission
from app.services import catalog_service as svc
from app.services.catalog_service import CatalogError
from app.services.quote_service import get_quote, provider_items, serialize_quote, update_quote_item
from app.services.quote_validation import QuoteValidationError

bp = Blueprint("catalog", __name__)


def _error(exc):
    return jsonify(error=exc.code, **exc.extra), exc.status


@bp.get("/catalog/offers")
@tenant_permission("catalog.read")
def list_offers():
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = min(max(request.args.get("per_page", 50, type=int) or 50, 1), 200)
    total, items = svc.list_catalog(
        g.tenant_id, category_id=request.args.get("category_id", type=int),
        search=request.args.get("search"), status=request.args.get("status"),
        include_inventory=request.args.get("include_inventory", "1") != "0",
        published_only=request.args.get("published_only") == "1", page=page, per_page=per_page)
    return jsonify(items=items, total=total, page=page, per_page=per_page), 200


@bp.get("/catalog/offers/<int:offer_id>")
@tenant_permission("catalog.read")
def get_offer(offer_id):
    from app.models.catalog import CatalogOffer
    offer = db.session.scalar(select(CatalogOffer).where(
        CatalogOffer.id == offer_id, CatalogOffer.tenant_id == g.tenant_id))
    if offer is None:
        return jsonify(error="offer_not_found"), 404
    categories, providers = svc._lookup_maps(g.tenant_id, [offer])
    return jsonify(offer=svc.offer_dict(offer, categories=categories, providers=providers)), 200


@bp.post("/catalog/offers")
@tenant_permission("catalog.manage")
def create_offer():
    try:
        offer = svc.save_offer(g.tenant_id, g.user.id, request.get_json(silent=True))
    except CatalogError as exc:
        db.session.rollback()
        return _error(exc)
    categories, providers = svc._lookup_maps(g.tenant_id, [offer])
    return jsonify(offer=svc.offer_dict(offer, categories=categories, providers=providers)), 201


@bp.patch("/catalog/offers/<int:offer_id>")
@tenant_permission("catalog.manage")
def update_offer(offer_id):
    try:
        offer = svc.save_offer(g.tenant_id, g.user.id, request.get_json(silent=True), offer_id)
    except CatalogError as exc:
        db.session.rollback()
        return _error(exc)
    categories, providers = svc._lookup_maps(g.tenant_id, [offer])
    return jsonify(offer=svc.offer_dict(offer, categories=categories, providers=providers)), 200


@bp.get("/providers")
@tenant_permission("catalog.read")
def list_providers():
    return jsonify(items=svc.list_providers(g.tenant_id)), 200


@bp.post("/providers")
@tenant_permission("catalog.manage")
def create_provider():
    try:
        provider = svc.save_provider(g.tenant_id, request.get_json(silent=True))
    except CatalogError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(provider=svc.provider_dict(provider)), 201


@bp.patch("/providers/<int:provider_id>")
@tenant_permission("catalog.manage")
def update_provider(provider_id):
    try:
        provider = svc.save_provider(g.tenant_id, request.get_json(silent=True), provider_id)
    except CatalogError as exc:
        db.session.rollback()
        return _error(exc)
    return jsonify(provider=svc.provider_dict(provider)), 200


# ----------------------------------------------------------------------------
# Portal del proveedor: solo sus propias partidas
# ----------------------------------------------------------------------------

def _provider_id():
    membership = getattr(g, "membership", None)
    return membership.provider_id if membership is not None else None


@bp.get("/provider/items")
@tenant_permission("provider.items")
def my_provider_items():
    provider_id = _provider_id()
    if provider_id is None:
        return jsonify(error="provider_not_linked"), 403
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    return jsonify(items=provider_items(g.tenant_id, provider_id, page=page)), 200


@bp.patch("/provider/items/<int:item_id>")
@tenant_permission("provider.items")
def update_my_provider_item(item_id):
    provider_id = _provider_id()
    if provider_id is None:
        return jsonify(error="provider_not_linked"), 403
    quote_id = db.session.scalar(select(QuoteItem.quote_id).where(
        QuoteItem.id == item_id, QuoteItem.tenant_id == g.tenant_id, QuoteItem.provider_id == provider_id))
    if quote_id is None:
        return jsonify(error="validation_error", details={"item": "not_found"}), 404
    try:
        update_quote_item(g.tenant_id, quote_id, item_id, g.user.id, request.get_json(silent=True),
                          provider_id=provider_id)
        db.session.commit()
    except QuoteValidationError as exc:
        db.session.rollback()
        return jsonify(error="validation_error", details=exc.details), exc.status_code
    items = [i for i in provider_items(g.tenant_id, provider_id, per_page=500) if i["id"] == item_id]
    return jsonify(item=items[0] if items else None), 200
