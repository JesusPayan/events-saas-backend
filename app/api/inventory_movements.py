
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_movement import InventoryMovement
from app.security import tenant_permission
from flask_jwt_extended import (
    jwt_required,
    get_jwt_identity
)
from app.services.inventory_movements import (
    get_movement_summary
)


bp = Blueprint("inventory_movements", __name__)


def get_reservation_for_update(reservation_id):
    """
    Bloquea primero el artículo y después la reserva.
    Se usa el mismo orden que en las operaciones
    de creación y cancelación.
    """

    # Identificar la reserva y el artículo.
    reservation = db.session.scalar(
        select(InventoryReservation).where(
            InventoryReservation.id == reservation_id,
            InventoryReservation.tenant_id == g.tenant_id
        )
    )

    if reservation is None:
        return None

    # Bloquear el artículo.
    item = db.session.scalar(
        select(InventoryItem)
        .where(
            InventoryItem.id == reservation.inventory_item_id,
            InventoryItem.tenant_id == g.tenant_id
        )
        .with_for_update()
    )

    if item is None:
        return None

    # Releer y bloquear la reserva.
    reservation = db.session.scalar(
        select(InventoryReservation)
        .where(
            InventoryReservation.id == reservation_id,
            InventoryReservation.tenant_id == g.tenant_id,
            InventoryReservation.inventory_item_id == item.id
        )
        .with_for_update()
    )

    return reservation


def get_event(reservation):
    return db.session.scalar(
        select(Event).where(
            Event.id == reservation.event_id,
            Event.tenant_id == g.tenant_id
        )
    )


def validate_payload():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return None, "invalid_json"

    reservation_id = data.get("reservation_id")
    quantity = data.get("quantity")

    if (
        type(reservation_id) is not int
        or type(quantity) is not int
    ):
        return None, "invalid_payload"

    if reservation_id <= 0 or quantity <= 0:
        return None, "invalid_quantity"

    notes = data.get("notes")

    if notes is not None:
        if (
            not isinstance(notes, str)
            or len(notes) > 2000
        ):
            return None, "invalid_notes"

    return {
        "reservation_id": reservation_id,
        "quantity": quantity,
        "notes": notes
    }, None


def register_movement(movement_type):
    payload, error = validate_payload()

    if error:
        return jsonify(error=error), 400

    try:
        reservation = get_reservation_for_update(
            payload["reservation_id"]
        )

        if reservation is None:
            db.session.rollback()
            return jsonify(
                error="reservation_not_found"
            ), 404

        event = get_event(reservation)

        if event is None:
            db.session.rollback()
            return jsonify(
                error="event_not_found"
            ), 404

        summary = get_movement_summary(
            g.tenant_id,
            reservation.id
        )

        quantity = payload["quantity"]

        if movement_type == "dispatch":

            if reservation.status != "reserved":
                db.session.rollback()
                return jsonify(
                    error="reservation_not_active"
                ), 409

            if event.status in (
                "cancelled",
                "completed"
            ):
                db.session.rollback()
                return jsonify(
                    error="event_not_dispatchable"
                ), 409

            remaining = (
                reservation.quantity
                - summary["quantity_dispatched"]
            )

            if quantity > remaining:
                db.session.rollback()

                return jsonify(
                    error="dispatch_exceeds_reservation",
                    available=max(remaining, 0)
                ), 409

        elif movement_type == "return":

            if summary["quantity_outstanding"] <= 0:
                db.session.rollback()
                return jsonify(
                    error="nothing_to_return"
                ), 409

            if quantity > summary["quantity_outstanding"]:
                db.session.rollback()

                return jsonify(
                    error="return_exceeds_outstanding",
                    outstanding=summary[
                        "quantity_outstanding"
                    ]
                ), 409

        else:
            db.session.rollback()
            return jsonify(
                error="invalid_movement_type"
            ), 400

        movement = InventoryMovement(
    tenant_id=g.tenant_id,
    inventory_item_id=reservation.inventory_item_id,
    reservation_id=reservation.id,
    movement_type=movement_type,
    quantity=quantity,
    notes=payload["notes"],
    created_by=g.user.id
)

        db.session.add(movement)

        # Guardar y recuperar el ID sin liberar bloqueos.
        db.session.flush()

        movement_data = movement.to_dict()

        db.session.commit()

        updated_summary = get_movement_summary(
            g.tenant_id,
            reservation.id
        )

        return jsonify({
            "movement": movement_data,
            "summary": updated_summary
        }), 201

    except IntegrityError:
        db.session.rollback()
        return jsonify(
            error="movement_conflict"
        ), 409

    except Exception:
        db.session.rollback()
        raise


# @bp.post("/inventory/movements/dispatch")
# @tenant_permission("inventory.update")
# def dispatch():
#     return register_movement("dispatch")


# @bp.post("/inventory/movements/return")
# @tenant_permission("inventory.update")
# def return_inventory():
#     return register_movement("return")


# @bp.get("/inventory/movements")
# @tenant_permission("inventory.read")
# def list_movements():

#     try:
#         reservation_id = int(
#             request.args.get("reservation_id", "")
#         )
#     except (TypeError, ValueError):
#         return jsonify(
#             error="invalid_reservation_id"
#         ), 400

#     if reservation_id <= 0:
#         return jsonify(
#             error="invalid_reservation_id"
#         ), 400

#     reservation = db.session.scalar(
#         select(InventoryReservation).where(
#             InventoryReservation.id == reservation_id,
#             InventoryReservation.tenant_id == g.tenant_id
#         )
#     )

#     if reservation is None:
#         return jsonify(
#             error="reservation_not_found"
#         ), 404

#     movements = db.session.scalars(
#         select(InventoryMovement)
#         .where(
#             InventoryMovement.tenant_id == g.tenant_id,
#             InventoryMovement.reservation_id == reservation_id
#         )
#         .order_by(
#             InventoryMovement.created_at.desc(),
#             InventoryMovement.id.desc()
#         )
#     ).all()

#     return jsonify({
#         "items": [
#             movement.to_dict()
#             for movement in movements
#         ],
#         "summary": get_movement_summary(
#             g.tenant_id,
#             reservation_id
#         )
#     }), 200

@bp.post("/inventory/movements/dispatch")
# @jwt_required()
@tenant_permission("inventory.update")
def dispatch():
    return register_movement("dispatch")


@bp.post("/inventory/movements/return")
# @jwt_required()
@tenant_permission("inventory.update")
def return_inventory():
    return register_movement("return")


@bp.get("/inventory/movements")
# @jwt_required()
@tenant_permission("inventory.read")
def list_movements():

    try:
        reservation_id = int(
            request.args.get("reservation_id", "")
        )
    except (TypeError, ValueError):
        return jsonify(
            error="invalid_reservation_id"
        ), 400

    if reservation_id <= 0:
        return jsonify(
            error="invalid_reservation_id"
        ), 400

    reservation = db.session.scalar(
        select(InventoryReservation).where(
            InventoryReservation.id == reservation_id,
            InventoryReservation.tenant_id == g.tenant_id
        )
    )

    if reservation is None:
        return jsonify(
            error="reservation_not_found"
        ), 404

    movements = db.session.scalars(
        select(InventoryMovement)
        .where(
            InventoryMovement.tenant_id == g.tenant_id,
            InventoryMovement.reservation_id == reservation_id
        )
        .order_by(
            InventoryMovement.created_at.desc(),
            InventoryMovement.id.desc()
        )
    ).all()

    return jsonify({
        "items": [
            movement.to_dict()
            for movement in movements
        ],
        "summary": get_movement_summary(
            g.tenant_id,
            reservation_id
        )
    }), 200
