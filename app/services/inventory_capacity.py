
from sqlalchemy import select

from app.extensions import db
from app.models.event import Event
from app.models.inventory_reservation import InventoryReservation


def get_max_concurrent_reserved(tenant_id, item_id):
    rows = db.session.execute(
        select(
            Event.starts_at,
            Event.ends_at,
            InventoryReservation.quantity
        )
        .join(
            InventoryReservation,
            InventoryReservation.event_id == Event.id
        )
        .where(
            Event.tenant_id == tenant_id,
            InventoryReservation.tenant_id == tenant_id,
            InventoryReservation.inventory_item_id == item_id,
            InventoryReservation.status == "reserved",
            Event.status != "cancelled",
            Event.ends_at > Event.starts_at
        )
    ).all()

    points = []

    for starts_at, ends_at, quantity in rows:
        # El final de un evento no se superpone
        # con otro que inicia exactamente a esa hora.
        points.append((starts_at, 1, int(quantity)))
        points.append((ends_at, 0, -int(quantity)))

    points.sort(key=lambda point: (point[0], point[1]))

    current = 0
    maximum = 0

    for _, _, delta in points:
        current += delta
        maximum = max(maximum, current)

    return maximum
