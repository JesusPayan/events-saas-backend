
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from sqlalchemy import select, func

from app.extensions import db
from app.models.event import Event
from app.models.crm import Client
from app.security import tenant_permission
from app.schemas.events import validate_event, parse_datetime

from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.services.inventory_reservations import get_availability
from datetime import datetime
from flask import request, jsonify


bp = Blueprint("events", __name__)

ALLOWED_TRANSITIONS = {
    "draft": {"quoted", "cancelled"},
    "quoted": {"confirmed", "cancelled"},
    "confirmed": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set()
}


def get_event_or_none(event_id):
    return db.session.scalar(
        select(Event).where(
            Event.id == event_id,
            Event.tenant_id == g.tenant_id
        )
    )


def client_exists(client_id):
    return db.session.scalar(
        select(Client.id).where(
            Client.id == client_id,
            Client.tenant_id == g.tenant_id
        )
    ) is not None
def parse_iso_date(value):
    if not value:
        return None

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


@bp.get("/events")
@tenant_permission("events.read")
def list_events():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(
        100,
        max(1, request.args.get("per_page", 20, type=int))
    )

    stmt = select(Event).where(Event.tenant_id == g.tenant_id)

    status = request.args.get("status")
    client_id = request.args.get("client_id", type=int)
    search = request.args.get("search", "").strip()

    if status:
        stmt = stmt.where(Event.status == status)

    if client_id:
        stmt = stmt.where(Event.client_id == client_id)

    if search:
        stmt = stmt.where(Event.name.ilike(f"%{search}%"))

    try:
        if request.args.get("from"):
            start = parse_datetime(request.args["from"])
            stmt = stmt.where(Event.starts_at >= start)

        if request.args.get("to"):
            end = parse_datetime(request.args["to"])
            stmt = stmt.where(Event.starts_at < end)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    stmt = stmt.order_by(Event.starts_at.desc(), Event.id.desc())

    result = db.paginate(
        stmt,
        page=page,
        per_page=per_page,
        error_out=False
    )

    return jsonify(
        items=[event.to_dict() for event in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages
    )


@bp.post("/events")
@tenant_permission("events.create")
def create_event():
    data = request.get_json(silent=True)
    cleaned, errors = validate_event(data)

    if errors:
        return jsonify(error="validation_error", details=errors), 400

    if not client_exists(cleaned["client_id"]):
        return jsonify(error="client_not_found"), 404

    event = Event(
        tenant_id=g.tenant_id,
        status="draft",
        **cleaned
    )

    db.session.add(event)
    db.session.commit()

    return jsonify(event.to_dict()), 201


@bp.get("/events/<int:event_id>")
@tenant_permission("events.read")
def get_event(event_id):
    event = get_event_or_none(event_id)

    if not event:
        return jsonify(error="not_found"), 404

    return jsonify(event.to_dict())
@bp.get("/events/calendar")
@tenant_permission("events.read")
def calendar_events():
    from_value = request.args.get("from")
    to_value = request.args.get("to")

    if not from_value or not to_value:
        return jsonify(error="date_range_required"), 400

    try:
        start = parse_datetime(from_value)
        end = parse_datetime(to_value)
    except (ValueError, TypeError):
        return jsonify(error="invalid_date_range"), 400

    if end <= start:
        return jsonify(error="invalid_date_range"), 400

    if (end - start).total_seconds() > 62 * 24 * 60 * 60:
        return jsonify(error="range_too_large"), 400

    events = db.session.scalars(
        select(Event)
        .where(
            Event.tenant_id == g.tenant_id,
            Event.starts_at < end,
            Event.ends_at > start
        )
        .order_by(Event.starts_at.asc(), Event.id.asc())
    ).all()

    return jsonify([
        event.to_dict()
        for event in events
    ]), 200



@bp.patch("/events/<int:event_id>")
@tenant_permission("events.update")
def update_event(event_id):
    try:
        data = request.get_json(silent=True)

        cleaned, errors = validate_event(
            data,
            partial=True
        )

        if errors:
            return jsonify(
                error="validation_error",
                details=errors
            ), 400

        # Bloquear el evento durante la modificación.
        event = db.session.scalar(
            select(Event)
            .where(
                Event.id == event_id,
                Event.tenant_id == g.tenant_id
            )
            .with_for_update()
        )

        if event is None:
            db.session.rollback()
            return jsonify(error="not_found"), 404

        if event.status in ("completed", "cancelled"):
            db.session.rollback()
            return jsonify(error="event_locked"), 409

        if (
            "client_id" in cleaned
            and not client_exists(cleaned["client_id"])
        ):
            db.session.rollback()
            return jsonify(error="client_not_found"), 404

        start = cleaned.get(
            "starts_at",
            event.starts_at
        )

        end = cleaned.get(
            "ends_at",
            event.ends_at
        )

        if end <= start:
            db.session.rollback()
            return jsonify(
                error="validation_error",
                details={
                    "ends_at": "must_be_after_start"
                }
            ), 400

        dates_changed = (
            start != event.starts_at
            or end != event.ends_at
        )

        if dates_changed:
            # Identificar artículos reservados.
            item_ids = db.session.scalars(
                select(
                    InventoryReservation.inventory_item_id
                )
                .where(
                    InventoryReservation.tenant_id == g.tenant_id,
                    InventoryReservation.event_id == event_id,
                    InventoryReservation.status == "reserved"
                )
                .order_by(
                    InventoryReservation.inventory_item_id
                )
            ).all()

            # Bloquear artículos en orden estable.
            for item_id in sorted(set(item_ids)):
                item = db.session.scalar(
                    select(InventoryItem)
                    .where(
                        InventoryItem.id == item_id,
                        InventoryItem.tenant_id == g.tenant_id
                    )
                    .with_for_update()
                )

                if item is None:
                    db.session.rollback()
                    return jsonify(
                        error="inventory_item_not_found",
                        inventory_item_id=item_id
                    ), 409

                reservation = db.session.scalar(
                    select(InventoryReservation)
                    .where(
                        InventoryReservation.tenant_id == g.tenant_id,
                        InventoryReservation.event_id == event_id,
                        InventoryReservation.inventory_item_id == item_id,
                        InventoryReservation.status == "reserved"
                    )
                )

                if reservation is None:
                    continue

                availability = get_availability(
                    tenant_id=g.tenant_id,
                    item_id=item_id,
                    starts_at=start,
                    ends_at=end,
                    exclude_event_id=event_id
                )

                if (
                    reservation.quantity
                    > availability["quantity_available"]
                ):
                    db.session.rollback()
                    return jsonify(
                        error="inventory_conflict",
                        inventory_item_id=item_id,
                        requested=reservation.quantity,
                        available=availability["quantity_available"]
                    ), 409

        # Aplicar cambios solamente después
        # de validar el inventario.
        for field, value in cleaned.items():
            setattr(event, field, value)

        db.session.commit()

        return jsonify(event.to_dict()), 200

    except Exception:
        db.session.rollback()
        raise



@bp.patch("/events/<int:event_id>/status")
@tenant_permission("events.update")
def update_event_status(event_id):
    event = get_event_or_none(event_id)

    if not event:
        return jsonify(error="not_found"), 404

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400

    new_status = data.get("status")

    if new_status not in ALLOWED_TRANSITIONS.get(event.status, set()):
        return jsonify(error="invalid_status_transition"), 409

    event.status = new_status
    db.session.commit()

    return jsonify(event.to_dict())



    return jsonify([event.to_dict() for event in events])

