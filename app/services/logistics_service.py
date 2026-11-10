
from collections import defaultdict

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.logistics_order import LogisticsOrder
from app.models.logistics_order_item import LogisticsOrderItem
from app.models.inventory_reservation import InventoryReservation


class LogisticsError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def create_order(tenant_id, event_id, user_id, scheduled_at=None, notes=None):
    # Evitar órdenes activas duplicadas por evento.
    # Para concurrencia real, complementar con una restricción
    # o mecanismo de bloqueo transaccional.
    existing = LogisticsOrder.query.filter(
        LogisticsOrder.tenant_id == tenant_id,
        LogisticsOrder.event_id == event_id,
        LogisticsOrder.status != "cancelled",
    ).first()

    if existing:
        raise LogisticsError(
            "El evento ya tiene una orden logística activa",
            409,
        )

    reservations = InventoryReservation.query.filter_by(
        tenant_id=tenant_id,
        event_id=event_id,
        status="reserved",
    ).all()

    if not reservations:
        raise LogisticsError(
            "El evento no tiene reservas activas de inventario",
            400,
        )

    quantities = defaultdict(int)

    for reservation in reservations:
        quantities[reservation.inventory_item_id] += reservation.quantity

    order = LogisticsOrder(
        tenant_id=tenant_id,
        event_id=event_id,
        created_by=user_id,
        scheduled_at=scheduled_at,
        notes=notes,
        status="pending",
    )

    try:
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

        db.session.commit()
        return order

    except IntegrityError:
        db.session.rollback()
        raise LogisticsError(
            "No se pudo crear la orden por una restricción de datos",
            409,
        )

    except Exception:
        db.session.rollback()
        raise


def get_order(tenant_id, order_id):
    order = LogisticsOrder.query.filter_by(
        tenant_id=tenant_id,
        id=order_id,
    ).first()

    if order is None:
        raise LogisticsError("Orden no encontrada", 404)

    return order


def update_prepared_quantity(
    tenant_id,
    order_id,
    item_id,
    quantity,
):
    if type(quantity) is not int or quantity < 0:
        raise LogisticsError(
            "La cantidad preparada debe ser un entero no negativo"
        )

    try:
        # Bloquear la orden durante la actualización.
        order = (
            LogisticsOrder.query
            .filter_by(tenant_id=tenant_id, id=order_id)
            .with_for_update()
            .first()
        )

        if order is None:
            raise LogisticsError("Orden no encontrada", 404)

        if order.status not in ("pending", "in_progress"):
            raise LogisticsError(
                "No se puede modificar una orden finalizada"
            )

        item = LogisticsOrderItem.query.filter_by(
            tenant_id=tenant_id,
            logistics_order_id=order_id,
            id=item_id,
        ).first()

        if item is None:
            raise LogisticsError("Artículo no encontrado", 404)

        if quantity > item.quantity_required:
            raise LogisticsError(
                "La cantidad preparada supera la requerida"
            )

        item.quantity_prepared = quantity

        if order.status == "pending":
            order.status = "in_progress"

        db.session.commit()
        return item

    except Exception:
        db.session.rollback()
        raise


def change_status(tenant_id, order_id, new_status):
    transitions = {
        "pending": {"in_progress", "cancelled"},
        "in_progress": {"prepared", "cancelled"},
        "prepared": set(),
        "cancelled": set(),
    }

    try:
        order = (
            LogisticsOrder.query
            .filter_by(tenant_id=tenant_id, id=order_id)
            .with_for_update()
            .first()
        )

        if order is None:
            raise LogisticsError("Orden no encontrada", 404)

        if new_status not in transitions.get(order.status, set()):
            raise LogisticsError(
                "Transición de estado no permitida",
                409,
            )

        if new_status == "prepared":
            items = LogisticsOrderItem.query.filter_by(
                tenant_id=tenant_id,
                logistics_order_id=order_id,
            ).all()

            if not items or any(
                item.quantity_prepared != item.quantity_required
                for item in items
            ):
                raise LogisticsError(
                    "Todos los artículos deben estar preparados"
                )

        order.status = new_status
        db.session.commit()
        return order

    except Exception:
        db.session.rollback()
        raise
