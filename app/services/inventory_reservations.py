
from sqlalchemy import select, func

from app.extensions import db
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation


BLOCKING_STATUSES = ("reserved",)


def validate_date_range(starts_at, ends_at):
    if starts_at is None or ends_at is None:
        raise ValueError("date_range_required")

    if ends_at <= starts_at:
        raise ValueError("invalid_date_range")

def get_reserved_quantity(
    tenant_id,
    item_id,
    starts_at,
    ends_at,
    exclude_event_id=None,
):
    """
    Calcula las unidades reservadas mediante una
    lectura actual con bloqueo en MySQL/InnoDB.

    Debe ejecutarse dentro de la misma transacción
    que mantiene bloqueado InventoryItem.
    """

    validate_date_range(starts_at, ends_at)

    query = (
        select(InventoryReservation.quantity)
        .join(
            Event,
            Event.id == InventoryReservation.event_id,
        )
        .where(
            InventoryReservation.tenant_id == tenant_id,
            Event.tenant_id == tenant_id,
            InventoryReservation.inventory_item_id == item_id,
            InventoryReservation.status.in_(BLOCKING_STATUSES),
            Event.status != "cancelled",
            Event.starts_at < ends_at,
            Event.ends_at > starts_at,
        )
    )

    if exclude_event_id is not None:
        query = query.where(
            InventoryReservation.event_id != exclude_event_id
        )

    quantities = db.session.scalars(
        query.with_for_update()
    ).all()

    return sum(
        int(quantity)
        for quantity in quantities
    )

def get_availability(
    tenant_id,
    item_id,
    starts_at,
    ends_at,
    exclude_event_id=None
):
    validate_date_range(starts_at, ends_at)

    item = db.session.scalar(
        select(InventoryItem).where(
            InventoryItem.id == item_id,
            InventoryItem.tenant_id == tenant_id
        )
    )

    if item is None:
        return None

    reserved = get_reserved_quantity(
        tenant_id=tenant_id,
        item_id=item_id,
        starts_at=starts_at,
        ends_at=ends_at,
        exclude_event_id=exclude_event_id
    )

    total = int(item.quantity_total or 0)
    unavailable = int(item.quantity_unavailable or 0)

    # Inventario utilizable físicamente.
    rentable = max(total - unavailable, 0)

    # Disponibilidad para el periodo solicitado.
    available = max(rentable - reserved, 0)

    return {
        "inventory_item_id": item.id,
        "sku": item.sku,
        "name": item.name,
        "is_active": item.is_active,
        "quantity_total": total,
        "quantity_unavailable": unavailable,
        "quantity_rentable": rentable,
        "quantity_reserved": reserved,
        "quantity_available": available,
        "inventory_shortage": max(reserved - rentable, 0)
    }
