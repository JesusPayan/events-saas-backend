
from datetime import datetime, timezone

from flask import Blueprint, jsonify, g, request
from sqlalchemy import select

from app.extensions import db
from app.security import tenant_permission
from app.models.logistics_order import LogisticsOrder

from app.services.logistics_service import (
    LogisticsError,
    create_order as service_create_order,
    get_order as service_get_order,
    update_prepared_quantity,
    change_status,
    dispatch_order,
    deliver_order,
    get_order_history,
)

bp = Blueprint("logistics", __name__)


def iso_utc(value):
    if value is None:
        return None

    return value.isoformat() + "Z"


def serialize_item(item):
    return {
        "id": item.id,
        "inventory_item_id": item.inventory_item_id,
        "quantity_required": item.quantity_required,
        "quantity_prepared": item.quantity_prepared,
    }


def serialize_order(order):
    return {
        "id": order.id,
        "tenant_id": order.tenant_id,
        "event_id": order.event_id,
        "status": order.status,
        "scheduled_at": iso_utc(order.scheduled_at),
        "notes": order.notes,
        "created_by": order.created_by,
        "created_at": iso_utc(order.created_at),
        "updated_at": iso_utc(order.updated_at),
        "dispatched_at": iso_utc(order.dispatched_at),
        "dispatched_by": order.dispatched_by,
        "dispatch_notes": order.dispatch_notes,
        "delivered_at": iso_utc(order.delivered_at),
        "delivered_by": order.delivered_by,
        "delivery_notes": order.delivery_notes,
        "items": [
            serialize_item(item)
            for item in sorted(order.items, key=lambda x: x.id)
        ],
    }


def serialize_history(entry):
    return {
        "id": entry.id,
        "logistics_order_id": entry.logistics_order_id,
        "previous_status": entry.previous_status,
        "new_status": entry.new_status,
        "changed_by": entry.changed_by,
        "notes": entry.notes,
        "created_at": iso_utc(entry.created_at),
    }


def parse_datetime(value):
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError("invalid_scheduled_at")

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        raise ValueError("invalid_scheduled_at")

    if parsed.tzinfo is None:
        raise ValueError("invalid_scheduled_at")

    return parsed.astimezone(
        timezone.utc
    ).replace(tzinfo=None)


def parse_notes(data):
    notes = data.get("notes")

    if notes is not None:
        if not isinstance(notes, str) or len(notes) > 5000:
            raise ValueError("invalid_notes")

        notes = notes.strip() or None

    return notes


def read_json_object():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return None

    return data


@bp.errorhandler(LogisticsError)
def handle_logistics_error(error):
    db.session.rollback()

    return jsonify(
        error="logistics_error",
        message=str(error),
    ), error.status_code


@bp.get("/logistics/orders")
@tenant_permission("inventory.read")
def list_orders():
    event_id = request.args.get("event_id", type=int)
    status = request.args.get("status")

    query = select(LogisticsOrder).where(
        LogisticsOrder.tenant_id == g.tenant_id
    )

    if event_id is not None:
        if event_id <= 0:
            return jsonify(error="invalid_event_id"), 400

        query = query.where(
            LogisticsOrder.event_id == event_id
        )

    allowed_statuses = {
        "pending",
        "in_progress",
        "prepared",
        "dispatched",
        "delivered",
        "cancelled",
    }

    if status is not None:
        if status not in allowed_statuses:
            return jsonify(error="invalid_status"), 400

        query = query.where(
            LogisticsOrder.status == status
        )

    orders = db.session.scalars(
        query.order_by(LogisticsOrder.id.desc())
    ).all()

    return jsonify([
        serialize_order(order) for order in orders
    ]), 200


@bp.get("/logistics/orders/<int:order_id>")
@tenant_permission("inventory.read")
def get_order(order_id):
    order = service_get_order(g.tenant_id, order_id)

    return jsonify(serialize_order(order)), 200


@bp.post("/logistics/orders")
@tenant_permission("inventory.create")
def create_order():
    data = read_json_object()

    if data is None:
        return jsonify(error="invalid_json"), 400

    event_id = data.get("event_id")

    if type(event_id) is not int or event_id <= 0:
        return jsonify(error="invalid_event_id"), 400

    try:
        notes = parse_notes(data)
        scheduled_at = parse_datetime(
            data.get("scheduled_at")
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    order = service_create_order(
        tenant_id=g.tenant_id,
        event_id=event_id,
        user_id=g.user.id,
        scheduled_at=scheduled_at,
        notes=notes,
    )

    return jsonify(serialize_order(order)), 201


@bp.patch("/logistics/orders/<int:order_id>/items/<int:item_id>")
@tenant_permission("inventory.update")
def update_order_item(order_id, item_id):
    data = read_json_object()

    if data is None:
        return jsonify(error="invalid_json"), 400

    quantity = data.get("quantity_prepared")

    if type(quantity) is not int or quantity < 0:
        return jsonify(error="invalid_quantity"), 400

    update_prepared_quantity(
        tenant_id=g.tenant_id,
        order_id=order_id,
        item_id=item_id,
        quantity=quantity,
        user_id=g.user.id,
    )

    order = service_get_order(g.tenant_id, order_id)

    return jsonify(serialize_order(order)), 200


@bp.patch("/logistics/orders/<int:order_id>/status")
@tenant_permission("inventory.update")
def update_order_status(order_id):
    data = read_json_object()

    if data is None:
        return jsonify(error="invalid_json"), 400

    new_status = data.get("status")

    if not isinstance(new_status, str) or new_status not in (
        "in_progress",
        "prepared",
        "cancelled",
    ):
        return jsonify(error="invalid_status"), 400

    try:
        notes = parse_notes(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    order = change_status(
        tenant_id=g.tenant_id,
        order_id=order_id,
        new_status=new_status,
        user_id=g.user.id,
        notes=notes,
    )

    return jsonify(serialize_order(order)), 200


@bp.post("/logistics/orders/<int:order_id>/dispatch")
@tenant_permission("inventory.update")
def dispatch_logistics_order(order_id):
    data = read_json_object()

    if data is None:
        return jsonify(error="invalid_json"), 400

    try:
        notes = parse_notes(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    order = dispatch_order(
        tenant_id=g.tenant_id,
        order_id=order_id,
        user_id=g.user.id,
        notes=notes,
    )

    return jsonify(serialize_order(order)), 200


@bp.post("/logistics/orders/<int:order_id>/deliver")
@tenant_permission("inventory.update")
def deliver_logistics_order(order_id):
    data = read_json_object()

    if data is None:
        return jsonify(error="invalid_json"), 400

    try:
        notes = parse_notes(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    order = deliver_order(
        tenant_id=g.tenant_id,
        order_id=order_id,
        user_id=g.user.id,
        notes=notes,
    )

    return jsonify(serialize_order(order)), 200


@bp.get("/logistics/orders/<int:order_id>/history")
@tenant_permission("inventory.read")
def logistics_order_history(order_id):
    history = get_order_history(
        tenant_id=g.tenant_id,
        order_id=order_id,
    )

    return jsonify([
        serialize_history(entry) for entry in history
    ]), 200