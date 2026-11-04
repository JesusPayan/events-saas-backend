
from flask import Blueprint, jsonify, g, request
from sqlalchemy import select

from app.extensions import db
from app.security import tenant_permission
from app.models.inventory_capacity_alert import InventoryCapacityAlert
from app.models.inventory_capacity_alert_event import InventoryCapacityAlertEvent


bp = Blueprint("inventory_capacity_alert_events", __name__)


@bp.get("/inventory/capacity-alerts/<int:alert_id>/events")
@tenant_permission("inventory.read")
def list_alert_events(alert_id):

    alert = db.session.scalar(
        select(InventoryCapacityAlert).where(
            InventoryCapacityAlert.id == alert_id,
            InventoryCapacityAlert.tenant_id == g.tenant_id
        )
    )

    if alert is None:
        return jsonify(error="capacity_alert_not_found"), 404

    try:
        page = int(request.args.get("page", "1"))
        per_page = int(request.args.get("per_page", "20"))
    except (TypeError, ValueError):
        return jsonify(error="invalid_pagination"), 400

    if page < 1 or not 1 <= per_page <= 100:
        return jsonify(error="invalid_pagination"), 400

    query = (
        select(InventoryCapacityAlertEvent)
        .where(
            InventoryCapacityAlertEvent.tenant_id == g.tenant_id,
            InventoryCapacityAlertEvent.alert_id == alert_id
        )
        .order_by(
            InventoryCapacityAlertEvent.created_at.desc(),
            InventoryCapacityAlertEvent.id.desc()
        )
    )

    result = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    return jsonify({
        "items": [event.to_dict() for event in result.items],
        "total": result.total,
        "page": result.page,
        "per_page": result.per_page,
        "pages": result.pages
    }), 200
