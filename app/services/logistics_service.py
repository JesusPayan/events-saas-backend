
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.event import Event
from app.models.inventory_reservation import InventoryReservation
from app.models.logistics_order import LogisticsOrder, utc_now
from app.models.logistics_order_item import LogisticsOrderItem
from app.models.logistics_order_status_history import (
    LogisticsOrderStatusHistory,
)


class LogisticsError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


TRANSITIONS = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"prepared", "cancelled"},
    "prepared": {"dispatched"},
    "dispatched": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


def _locked_order(tenant_id, order_id):
    order = db.session.scalar(
        select(LogisticsOrder)
        .where(
            LogisticsOrder.tenant_id == tenant_id,
            LogisticsOrder.id == order_id,
        )
        .with_for_update()
    )

    if order is None:
        raise LogisticsError("Orden no encontrada", 404)

    return order


def _record_history(order, previous_status, user_id, notes=None):
    if type(user_id) is not int or user_id <= 0:
        raise LogisticsError("Usuario inválido", 400)

    db.session.add(
        LogisticsOrderStatusHistory(
            tenant_id=order.tenant_id,
            logistics_order_id=order.id,
            previous_status=previous_status,
            new_status=order.status,
            changed_by=user_id,
            notes=notes,
            created_at=utc_now(),
        )
    )


def create_order(
    tenant_id,
    event_id,
    user_id,
    scheduled_at=None,
    notes=None,
):
    try:
        event = db.session.scalar(
            select(Event)
            .where(
                Event.id == event_id,
                Event.tenant_id == tenant_id,
            )
            .with_for_update()
        )

        if event is None:
            raise LogisticsError("Evento no encontrado", 404)

        if event.status in ("cancelled", "completed"):
            raise LogisticsError(
                "No se pueden preparar eventos finalizados", 409
            )

        existing = db.session.scalar(
            select(LogisticsOrder).where(
                LogisticsOrder.tenant_id == tenant_id,
                LogisticsOrder.event_id == event_id,
                LogisticsOrder.status != "cancelled",
            )
        )

        if existing is not None:
            raise LogisticsError(
                "El evento ya tiene una orden logística activa", 409
            )

        reservations = db.session.scalars(
            select(InventoryReservation).where(
                InventoryReservation.tenant_id == tenant_id,
                InventoryReservation.event_id == event_id,
                InventoryReservation.status == "reserved",
            )
        ).all()

        if not reservations:
            raise LogisticsError(
                "El evento no tiene reservas activas", 409
            )

        quantities = defaultdict(int)

        for reservation in reservations:
            quantities[reservation.inventory_item_id] += (
                reservation.quantity
            )

        order = LogisticsOrder(
            tenant_id=tenant_id,
            event_id=event_id,
            created_by=user_id,
            scheduled_at=scheduled_at,
            notes=notes,
            status="pending",
        )

        db.session.add(order)
        db.session.flush()

        for inventory_item_id, quantity in quantities.items():
            db.session.add(
                LogisticsOrderItem(
                    tenant_id=tenant_id,
                    logistics_order_id=order.id,
                    inventory_item_id=inventory_item_id,
                    quantity_required=quantity,
                    quantity_prepared=0,
                )
            )

        _record_history(
            order=order,
            previous_status=None,
            user_id=user_id,
            notes="Orden logística creada",
        )

        db.session.commit()
        return order

    except IntegrityError:
        db.session.rollback()
        raise LogisticsError(
            "Conflicto al crear la orden logística", 409
        )

    except Exception:
        db.session.rollback()
        raise


def get_order(tenant_id, order_id):
    order = db.session.scalar(
        select(LogisticsOrder).where(
            LogisticsOrder.tenant_id == tenant_id,
            LogisticsOrder.id == order_id,
        )
    )

    if order is None:
        raise LogisticsError("Orden no encontrada", 404)

    return order


def update_prepared_quantity(
    tenant_id,
    order_id,
    item_id,
    quantity,
    user_id=None,
):
    if type(quantity) is not int or quantity < 0:
        raise LogisticsError(
            "La cantidad preparada debe ser un entero no negativo"
        )

    try:
        order = _locked_order(tenant_id, order_id)

        if order.status not in ("pending", "in_progress"):
            raise LogisticsError(
                "No se puede modificar una orden finalizada", 409
            )

        item = db.session.scalar(
            select(LogisticsOrderItem).where(
                LogisticsOrderItem.tenant_id == tenant_id,
                LogisticsOrderItem.logistics_order_id == order_id,
                LogisticsOrderItem.id == item_id,
            )
        )

        if item is None:
            raise LogisticsError("Artículo no encontrado", 404)

        if quantity > item.quantity_required:
            raise LogisticsError(
                "La cantidad preparada supera la requerida"
            )

        previous_status = order.status
        item.quantity_prepared = quantity

        if order.status == "pending":
            if user_id is None:
                raise LogisticsError(
                    "Se requiere usuario para iniciar preparación"
                )

            order.status = "in_progress"

            _record_history(
                order,
                previous_status,
                user_id,
                "Preparación iniciada al registrar un artículo",
            )

        db.session.commit()
        return item

    except Exception:
        db.session.rollback()
        raise


def change_status(
    tenant_id,
    order_id,
    new_status,
    user_id,
    notes=None,
):
    try:
        order = _locked_order(tenant_id, order_id)

        previous_status = order.status

        if new_status not in TRANSITIONS.get(previous_status, set()):
            raise LogisticsError(
                "Transición de estado no permitida", 409
            )

        if new_status == "prepared":
            items = db.session.scalars(
                select(LogisticsOrderItem).where(
                    LogisticsOrderItem.tenant_id == tenant_id,
                    LogisticsOrderItem.logistics_order_id == order_id,
                )
            ).all()

            if not items or any(
                item.quantity_prepared != item.quantity_required
                for item in items
            ):
                raise LogisticsError(
                    "Todos los artículos deben estar preparados", 409
                )

        now = utc_now()

        if new_status == "dispatched":
            order.dispatched_at = now
            order.dispatched_by = user_id
            order.dispatch_notes = notes

        elif new_status == "delivered":
            order.delivered_at = now
            order.delivered_by = user_id
            order.delivery_notes = notes

        order.status = new_status
        order.updated_at = now

        _record_history(
            order=order,
            previous_status=previous_status,
            user_id=user_id,
            notes=notes,
        )

        db.session.commit()
        return order

    except Exception:
        db.session.rollback()
        raise


def dispatch_order(tenant_id, order_id, user_id, notes=None):
    return change_status(
        tenant_id=tenant_id,
        order_id=order_id,
        new_status="dispatched",
        user_id=user_id,
        notes=notes,
    )


def deliver_order(tenant_id, order_id, user_id, notes=None):
    return change_status(
        tenant_id=tenant_id,
        order_id=order_id,
        new_status="delivered",
        user_id=user_id,
        notes=notes,
    )


def get_order_history(tenant_id, order_id):
    # Primero comprobar que la orden pertenece al tenant.
    get_order(tenant_id, order_id)

    return db.session.scalars(
        select(LogisticsOrderStatusHistory)
        .where(
            LogisticsOrderStatusHistory.tenant_id == tenant_id,
            LogisticsOrderStatusHistory.logistics_order_id == order_id,
        )
        .order_by(
            LogisticsOrderStatusHistory.created_at.asc(),
            LogisticsOrderStatusHistory.id.asc(),
        )
    ).all()
