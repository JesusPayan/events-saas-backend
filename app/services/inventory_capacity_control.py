
from sqlalchemy import select

from app.extensions import db
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_capacity_alert import InventoryCapacityAlert
from app.models.inventory_capacity_alert import utc_now
from app.models.inventory_capacity_alert_event import (
    InventoryCapacityAlertEvent
)

def capacity_error():
    return ValueError("inventory_capacity_deficit_open")


def load_reservations(tenant_id, item_id):
    return db.session.execute(
        select(
            InventoryReservation.id,
            InventoryReservation.quantity,
            Event.starts_at,
            Event.ends_at
        )
        .join(
            Event,
            (Event.id == InventoryReservation.event_id)
            & (Event.tenant_id == InventoryReservation.tenant_id)
        )
        .where(
            InventoryReservation.tenant_id == tenant_id,
            InventoryReservation.inventory_item_id == item_id,
            InventoryReservation.status == "reserved",
            Event.status != "cancelled",
            Event.ends_at > Event.starts_at
        )
    ).all()


def maximum_demand(rows, start=None, end=None):
    points = []

    for reservation_id, quantity, starts_at, ends_at in rows:
        if start is not None:
            starts_at = max(starts_at, start)
        if end is not None:
            ends_at = min(ends_at, end)

        if starts_at >= ends_at:
            continue

        points.append((starts_at, 1, int(quantity)))
        points.append((ends_at, 0, -int(quantity)))

    # Procesar finales antes de inicios simultáneos.
    points.sort(key=lambda p: (p[0], p[1]))

    current = maximum = 0
    for _, _, delta in points:
        current += delta
        maximum = max(maximum, current)

    return maximum


def get_item_capacity(tenant_id, item_id):
    item = db.session.scalar(
        select(InventoryItem).where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.id == item_id
        )
    )
    if item is None:
        return None

    rows = load_reservations(tenant_id, item_id)
    usable = item.quantity_total - item.quantity_unavailable
    maximum = maximum_demand(rows)

    return {
        "inventory_item_id": item_id,
        "quantity_total": item.quantity_total,
        "quantity_unavailable": item.quantity_unavailable,
        "quantity_usable": usable,
        "max_reserved": maximum,
        "shortage_quantity": max(0, maximum - usable),
    }


# def synchronize_capacity_alerts(tenant_id, item_id):
#     """
#     Llamar dentro de la misma transacción que modifica el artículo,
#     después de obtener el bloqueo FOR UPDATE del InventoryItem.
#     No realiza commit.
#     """
#     capacity = get_item_capacity(tenant_id, item_id)
#     if capacity is None:
#         raise ValueError("item_not_found")

#     rows = load_reservations(tenant_id, item_id)
#     usable = capacity["quantity_usable"]

#     existing = {
#         alert.reservation_id: alert
#         for alert in db.session.scalars(
#             select(InventoryCapacityAlert).where(
#                 InventoryCapacityAlert.tenant_id == tenant_id,
#                 InventoryCapacityAlert.inventory_item_id == item_id
#             )
#         ).all()
#     }

#     active_ids = set()
#     affected = []

#     for reservation_id, quantity, starts_at, ends_at in rows:
#         required = maximum_demand(rows, starts_at, ends_at)
#         shortage = max(0, required - usable)
#         active_ids.add(reservation_id)

#         alert = existing.get(reservation_id)

#         if shortage > 0:
#             if alert is None:
#                 alert = InventoryCapacityAlert(
#                     tenant_id=tenant_id,
#                     inventory_item_id=item_id,
#                     reservation_id=reservation_id,
#                     required_quantity=required,
#                     available_quantity=usable,
#                     shortage_quantity=shortage,
#                     status="open"
#                 )
#                 db.session.add(alert)
#             else:
#                 if alert.status != "open":
#                     alert.detected_at = utc_now()
#                 alert.required_quantity = required
#                 alert.available_quantity = usable
#                 alert.shortage_quantity = shortage
#                 alert.status = "open"
#                 alert.resolved_at = None

#             affected.append({
#                 "reservation_id": reservation_id,
#                 "required_quantity": required,
#                 "available_quantity": usable,
#                 "shortage_quantity": shortage,
#             })

#         elif alert is not None and alert.status == "open":
#             alert.status = "resolved"
#             alert.resolved_at = utc_now()

#     for reservation_id, alert in existing.items():
#         if reservation_id not in active_ids and alert.status == "open":
#             alert.status = "resolved"
#             alert.resolved_at = utc_now()

#     db.session.flush()

#     return {
#         **capacity,
#         "affected_reservations": affected
#     }

def synchronize_capacity_alerts(
    tenant_id,
    item_id,
    source_type="system",
    source_id=None,
    created_by=None
):
    """
    Requiere InventoryItem bloqueado FOR UPDATE.

    Sincroniza alertas y registra su historial.
    No ejecuta commit.
    """

    capacity = get_item_capacity(tenant_id, item_id)

    if capacity is None:
        raise ValueError("item_not_found")

    rows = load_reservations(tenant_id, item_id)
    usable = capacity["quantity_usable"]

    existing = {
        alert.reservation_id: alert
        for alert in db.session.scalars(
            select(InventoryCapacityAlert).where(
                InventoryCapacityAlert.tenant_id == tenant_id,
                InventoryCapacityAlert.inventory_item_id == item_id
            )
        ).all()
    }

    active_ids = set()
    affected = []
    audit_changes = []

    def record_change(alert, action, previous, current):
        # Flush asigna ID a las alertas nuevas.
        db.session.flush()

        audit_changes.append(
            InventoryCapacityAlertEvent(
                tenant_id=tenant_id,
                alert_id=alert.id,
                action=action,
                previous_shortage=previous,
                new_shortage=current,
                source_type=source_type,
                source_id=source_id,
                created_by=created_by
            )
        )

    for reservation_id, quantity, starts_at, ends_at in rows:
        required = maximum_demand(
            rows,
            starts_at,
            ends_at
        )

        shortage = max(0, required - usable)
        active_ids.add(reservation_id)

        alert = existing.get(reservation_id)

        if shortage > 0:
            if alert is None:
                alert = InventoryCapacityAlert(
                    tenant_id=tenant_id,
                    inventory_item_id=item_id,
                    reservation_id=reservation_id,
                    required_quantity=required,
                    available_quantity=usable,
                    shortage_quantity=shortage,
                    status="open"
                )

                db.session.add(alert)

                record_change(
                    alert,
                    "opened",
                    0,
                    shortage
                )

            else:
                previous = alert.shortage_quantity
                previous_status = alert.status

                if previous_status != "open":
                    alert.detected_at = utc_now()

                alert.required_quantity = required
                alert.available_quantity = usable
                alert.shortage_quantity = shortage
                alert.status = "open"
                alert.resolved_at = None

                if previous_status != "open":
                    record_change(
                        alert,
                        "reopened",
                        previous,
                        shortage
                    )

                elif previous != shortage:
                    record_change(
                        alert,
                        "updated",
                        previous,
                        shortage
                    )

            affected.append({
                "reservation_id": reservation_id,
                "required_quantity": required,
                "available_quantity": usable,
                "shortage_quantity": shortage
            })

        elif alert is not None and alert.status == "open":
            previous = alert.shortage_quantity

            alert.status = "resolved"
            alert.resolved_at = utc_now()

            record_change(
                alert,
                "resolved",
                previous,
                0
            )

    for reservation_id, alert in existing.items():
        if reservation_id not in active_ids:
            if alert.status == "open":
                previous = alert.shortage_quantity

                alert.status = "resolved"
                alert.resolved_at = utc_now()

                record_change(
                    alert,
                    "resolved",
                    previous,
                    0
                )

    db.session.add_all(audit_changes)
    db.session.flush()

    return {
        **capacity,
        "affected_reservations": affected,
        "audit_events_created": len(audit_changes)
    }


def assert_new_reservation_allowed(tenant_id, item_id):
    """
    Ejecutar con InventoryItem bloqueado FOR UPDATE.
    Impide nuevas asignaciones mientras exista déficit abierto.
    """
    capacity = get_item_capacity(tenant_id, item_id)

    if capacity is None:
        raise ValueError("item_not_found")

    if capacity["shortage_quantity"] > 0:
        raise capacity_error()
