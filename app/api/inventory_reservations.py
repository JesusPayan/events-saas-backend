
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.security import tenant_permission

from app.services.inventory_reservations import (
    get_availability
)

from app.services.inventory_movements import (
    get_movement_summary
)


bp = Blueprint("inventory_reservations", __name__)


# ==================================================
# UTILIDADES
# ==================================================

def parse_datetime(value):
    if not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            return None

        return parsed.astimezone(
            timezone.utc
        ).replace(tzinfo=None)

    except ValueError:
        return None


# ==================================================
# DISPONIBILIDAD
# ==================================================

@bp.get("/inventory/availability")
@tenant_permission("inventory.read")
def availability():

    try:
        item_id = int(
            request.args.get("item_id", "")
        )
    except (TypeError, ValueError):
        return jsonify(error="invalid_item_id"), 400

    if item_id <= 0:
        return jsonify(error="invalid_item_id"), 400

    starts_at = parse_datetime(
        request.args.get("starts_at")
    )

    ends_at = parse_datetime(
        request.args.get("ends_at")
    )

    if (
        starts_at is None
        or ends_at is None
        or ends_at <= starts_at
    ):
        return jsonify(
            error="invalid_date_range"
        ), 400

    result = get_availability(
        g.tenant_id,
        item_id,
        starts_at,
        ends_at
    )

    if result is None:
        return jsonify(
            error="item_not_found"
        ), 404

    return jsonify(result), 200


# ==================================================
# LISTAR RESERVACIONES
# ==================================================

@bp.get("/events/<int:event_id>/reservations")
@tenant_permission("inventory.read")
def list_reservations(event_id):

    event = db.session.scalar(
        select(Event).where(
            Event.id == event_id,
            Event.tenant_id == g.tenant_id
        )
    )

    if event is None:
        return jsonify(
            error="event_not_found"
        ), 404

    reservations = db.session.scalars(
        select(InventoryReservation).where(
            InventoryReservation.event_id == event_id,
            InventoryReservation.tenant_id == g.tenant_id
        )
    ).all()

    return jsonify([
        reservation.to_dict()
        for reservation in reservations
    ]), 200


# ==================================================
# CREAR / ACTUALIZAR RESERVACIÓN
# ==================================================

@bp.post("/events/<int:event_id>/reservations")
@tenant_permission("inventory.create")
def create_reservation(event_id):

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(
            error="invalid_json"
        ), 400

    item_id = data.get("inventory_item_id")
    quantity = data.get("quantity")

    if (
        type(item_id) is not int
        or type(quantity) is not int
        or item_id <= 0
        or quantity <= 0
    ):
        return jsonify(
            error="invalid_payload"
        ), 400

    try:

        # 1. Bloquear artículo.
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
                error="item_not_found"
            ), 404

        if not item.is_active:
            db.session.rollback()
            return jsonify(
                error="item_inactive"
            ), 409

        # 2. Validar evento.
        event = db.session.scalar(
            select(Event).where(
                Event.id == event_id,
                Event.tenant_id == g.tenant_id
            )
        )

        if event is None:
            db.session.rollback()
            return jsonify(
                error="event_not_found"
            ), 404

        if event.status in (
            "cancelled",
            "completed"
        ):
            db.session.rollback()
            return jsonify(
                error="event_not_reservable"
            ), 409

        # 3. Consultar reservación existente.
        existing = db.session.scalar(
            select(InventoryReservation)
            .where(
                InventoryReservation.tenant_id
                == g.tenant_id,
                InventoryReservation.event_id
                == event_id,
                InventoryReservation.inventory_item_id
                == item_id
            )
            .with_for_update()
        )

        # 4. Validar disponibilidad.
        availability = get_availability(
            g.tenant_id,
            item_id,
            event.starts_at,
            event.ends_at,
            exclude_event_id=event_id
        )

        if availability is None:
            db.session.rollback()
            return jsonify(
                error="item_not_found"
            ), 404

        if quantity > availability["quantity_available"]:
            db.session.rollback()

            return jsonify(
                error="insufficient_inventory",
                available=availability[
                    "quantity_available"
                ],
                requested=quantity
            ), 409

        # 5. Actualizar reservación.
        if existing is not None:

            summary = get_movement_summary(
                g.tenant_id,
                existing.id
            )

            dispatched = summary[
                "quantity_dispatched"
            ]

            returned = summary[
                "quantity_returned"
            ]

            outstanding = summary[
    "quantity_administrative_outstanding"
]

            # No reducir por debajo de lo entregado.
            if quantity < dispatched:
                db.session.rollback()

                return jsonify(
                    error="quantity_below_dispatched",
                    quantity_dispatched=dispatched,
                    quantity_requested=quantity
                ), 409

            # No reactivar una reservación cancelada
            # con movimientos históricos.
            if (
                existing.status == "cancelled"
                and (
                    dispatched > 0
                    or returned > 0
                    or outstanding > 0
                )
            ):
                db.session.rollback()

                return jsonify(
                    error="reservation_has_movements"
                ), 409

            existing.quantity = quantity
            existing.status = "reserved"

            reservation = existing
            status_code = 200

        # 6. Crear reservación.
        else:

            reservation = InventoryReservation(
                tenant_id=g.tenant_id,
                event_id=event_id,
                inventory_item_id=item_id,
                quantity=quantity,
                status="reserved"
            )

            db.session.add(reservation)
            status_code = 201

        # 7. Confirmar.
        db.session.commit()

        return jsonify(
            reservation.to_dict()
        ), status_code

    except IntegrityError:
        db.session.rollback()

        return jsonify(
        error="reservation_conflict",
        message=(
            "No fue posible guardar la reservación "
            "debido a un conflicto de integridad."
        )
    ), 409

    except Exception:
        db.session.rollback()
        raise


# ==================================================
# CANCELAR RESERVACIÓN
# ==================================================

@bp.patch(
    "/events/<int:event_id>/reservations/"
    "<int:reservation_id>/cancel"
)
@tenant_permission("inventory.update")
def cancel_reservation(event_id, reservation_id):

    try:

        # 1. Localizar reservación dentro del tenant.
        reservation = db.session.scalar(
            select(InventoryReservation).where(
                InventoryReservation.id == reservation_id,
                InventoryReservation.event_id == event_id,
                InventoryReservation.tenant_id == g.tenant_id
            )
        )

        if reservation is None:
            db.session.rollback()
            return jsonify(
                error="reservation_not_found"
            ), 404

        # 2. Bloquear artículo.
        item = db.session.scalar(
            select(InventoryItem)
            .where(
                InventoryItem.id
                == reservation.inventory_item_id,
                InventoryItem.tenant_id
                == g.tenant_id
            )
            .with_for_update()
        )

        if item is None:
            db.session.rollback()
            return jsonify(
                error="item_not_found"
            ), 404

        # 3. Releer reservación bajo bloqueo.
        reservation = db.session.scalar(
            select(InventoryReservation)
            .where(
                InventoryReservation.id == reservation_id,
                InventoryReservation.event_id == event_id,
                InventoryReservation.tenant_id == g.tenant_id,
                InventoryReservation.inventory_item_id
                == item.id
            )
            .with_for_update()
        )

        if reservation is None:
            db.session.rollback()
            return jsonify(
                error="reservation_not_found"
            ), 404

        if reservation.status == "cancelled":
            db.session.rollback()
            return jsonify(
                error="already_cancelled"
            ), 409

        # 4. Consultar movimientos.
        summary = get_movement_summary(
            g.tenant_id,
            reservation.id
        )

        outstanding = summary[
            "quantity_outstanding"
        ]

        # 5. Validar devoluciones pendientes.
        if outstanding > 0:
            db.session.rollback()

            return jsonify(
                error="pending_returns",
                message=(
                    "No es posible cancelar la "
                    "reservación porque existen "
                    "artículos pendientes de devolución."
                ),
                quantity_outstanding=outstanding
            ), 409

        # 6. Cancelar.
        reservation.status = "cancelled"

        db.session.commit()

        return jsonify(
            reservation.to_dict()
        ), 200

    except Exception:
        db.session.rollback()
        raise
