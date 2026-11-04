
from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.security import tenant_permission
from app.services.inventory_replenishment_service import (
    replenish_inventory,
)
from sqlalchemy import select
from app.models.inventory_item import InventoryItem
from app.models.inventory_replenishment import InventoryReplenishment

bp = Blueprint("inventory_replenishments", __name__)


@bp.post("/inventory/items/<int:item_id>/replenishments")
@tenant_permission("inventory.update")
def create_replenishment(item_id):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400

    quantity = data.get("quantity")
    reason = data.get("reason")
    reference = data.get("reference")

    if type(quantity) is not int or quantity <= 0:
        return jsonify(
            error="invalid_replenishment_quantity"
        ), 400

    if not isinstance(reason, str) or not reason.strip():
        return jsonify(
            error="replenishment_reason_required"
        ), 400

    if len(reason.strip()) > 2000:
        return jsonify(
            error="replenishment_reason_too_long"
        ), 400

    if reference is not None:
        if not isinstance(reference, str) or len(reference) > 100:
            return jsonify(
                error="invalid_replenishment_reference"
            ), 400

    try:
        result = replenish_inventory(
            tenant_id=g.tenant_id,
            item_id=item_id,
            quantity=quantity,
            reason=reason,
            reference=reference,
            created_by=g.user.id,
        )

        db.session.commit()

        return jsonify(result), 201

    except ValueError as exc:
        db.session.rollback()

        code = str(exc)

        status_codes = {
            "item_not_found": 404,
            "invalid_replenishment_quantity": 400,
            "replenishment_reason_required": 400,
            "replenishment_reason_too_long": 400,
            "invalid_replenishment_reference": 400,
        }

        if code not in status_codes:
            raise

        return jsonify(error=code), status_codes[code]

    except IntegrityError:
        db.session.rollback()
        return jsonify(
            error="replenishment_conflict"
        ), 409

    except Exception:
        db.session.rollback()
        raise


@bp.get("/inventory/items/<int:item_id>/replenishments")
@tenant_permission("inventory.read")
def list_replenishments(item_id):

    item = db.session.scalar(
        select(InventoryItem).where(
            InventoryItem.id == item_id,
            InventoryItem.tenant_id == g.tenant_id
        )
    )

    if item is None:
        return jsonify(error="item_not_found"), 404

    try:
        page = int(request.args.get("page", "1"))
        per_page = int(request.args.get("per_page", "20"))
    except (TypeError, ValueError):
        return jsonify(error="invalid_pagination"), 400

    if page < 1 or not 1 <= per_page <= 100:
        return jsonify(error="invalid_pagination"), 400

    query = (
        select(InventoryReplenishment)
        .where(
            InventoryReplenishment.tenant_id == g.tenant_id,
            InventoryReplenishment.inventory_item_id == item_id
        )
        .order_by(
            InventoryReplenishment.created_at.desc(),
            InventoryReplenishment.id.desc()
        )
    )

    result = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    return jsonify({
        "items": [row.to_dict() for row in result.items],
        "total": result.total,
        "page": result.page,
        "per_page": result.per_page,
        "pages": result.pages
    }), 200
