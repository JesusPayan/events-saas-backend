
from datetime import datetime, timezone

from sqlalchemy import select, func, case, and_

from app.extensions import db
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_movement import InventoryMovement


def utc_now():
    return datetime.now(
        timezone.utc
    ).replace(tzinfo=None)


def serialize_datetime(value):
    if value is None:
        return None

    return value.isoformat(
        timespec="seconds"
    ) + "Z"


def movement_totals_subquery(tenant_id):
    """
    Agrupa entregas y devoluciones por reservación.
    """

    return (
        select(
            InventoryMovement.reservation_id.label(
                "reservation_id"
            ),
            func.sum(
                case(
                    (
                        InventoryMovement.movement_type == "dispatch",
                        InventoryMovement.quantity
                    ),
                    else_=0
                )
            ).label("dispatched"),
            func.sum(
                case(
                    (
                        InventoryMovement.movement_type == "return",
                        InventoryMovement.quantity
                    ),
                    else_=0
                )
            ).label("returned")
        )
        .where(
            InventoryMovement.tenant_id == tenant_id
        )
        .group_by(
            InventoryMovement.reservation_id
        )
        .subquery()
    )


def build_operations_query(
    tenant_id,
    date_from=None,
    date_to=None,
    event_id=None,
    item_id=None,
    status="all"
):
    totals = movement_totals_subquery(tenant_id)

    dispatched = func.coalesce(
        totals.c.dispatched, 0
    )

    returned = func.coalesce(
        totals.c.returned, 0
    )

    outstanding = dispatched - returned

    pending_dispatch = (
        InventoryReservation.quantity - dispatched
    )

    now = utc_now()

    stmt = (
        select(
            InventoryReservation,
            Event,
            InventoryItem,
            dispatched.label("dispatched"),
            returned.label("returned")
        )
        .join(
            Event,
            and_(
                Event.id == InventoryReservation.event_id,
                Event.tenant_id
                == InventoryReservation.tenant_id
            )
        )
        .join(
            InventoryItem,
            and_(
                InventoryItem.id
                == InventoryReservation.inventory_item_id,
                InventoryItem.tenant_id
                == InventoryReservation.tenant_id
            )
        )
        .outerjoin(
            totals,
            totals.c.reservation_id
            == InventoryReservation.id
        )
        .where(
            InventoryReservation.tenant_id == tenant_id
        )
    )

    # Eventos que se superponen al periodo solicitado.
    if date_from is not None:
        stmt = stmt.where(
            Event.ends_at > date_from
        )

    if date_to is not None:
        stmt = stmt.where(
            Event.starts_at < date_to
        )

    if event_id is not None:
        stmt = stmt.where(
            Event.id == event_id
        )

    if item_id is not None:
        stmt = stmt.where(
            InventoryItem.id == item_id
        )

    if status == "pending_dispatch":
        stmt = stmt.where(
            InventoryReservation.status == "reserved",
            Event.status.notin_(
                ["cancelled", "completed"]
            ),
            pending_dispatch > 0
        )

    elif status == "pending_return":
        stmt = stmt.where(
            outstanding > 0
        )

    elif status == "overdue_return":
        stmt = stmt.where(
            outstanding > 0,
            Event.ends_at < now
        )

    elif status != "all":
        raise ValueError(
            "invalid_operation_status"
        )

    return stmt


def serialize_operation(
    reservation,
    event,
    item,
    dispatched,
    returned
):
    dispatched = int(dispatched or 0)
    returned = int(returned or 0)

    quantity_reserved = int(
        reservation.quantity
    )

    outstanding = max(
        0,
        dispatched - returned
    )

    dispatch_allowed = (
        reservation.status == "reserved"
        and event.status not in (
            "cancelled",
            "completed"
        )
    )

    pending_dispatch = (
        max(0, quantity_reserved - dispatched)
        if dispatch_allowed
        else 0
    )

    is_overdue = (
        outstanding > 0
        and event.ends_at is not None
        and event.ends_at < utc_now()
    )

    return {
        "reservation_id": reservation.id,
        "event_id": event.id,
        "inventory_item_id": item.id,
        "item_name": item.name,
        "item_sku": item.sku,
        "event_status": event.status,
        "reservation_status": reservation.status,
        "starts_at": serialize_datetime(
            event.starts_at
        ),
        "ends_at": serialize_datetime(
            event.ends_at
        ),
        "quantity_reserved": quantity_reserved,
        "quantity_dispatched": dispatched,
        "quantity_returned": returned,
        "quantity_pending_dispatch": pending_dispatch,
        "quantity_outstanding": outstanding,
        "is_overdue": is_overdue
    }


def get_operations(
    tenant_id,
    date_from=None,
    date_to=None,
    event_id=None,
    item_id=None,
    status="all",
    page=1,
    per_page=50
):
    stmt = build_operations_query(
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
        event_id=event_id,
        item_id=item_id,
        status=status
    )

    # Conteo sin paginación.
    count_stmt = select(
        func.count()
    ).select_from(
        stmt.order_by(None).subquery()
    )

    total = db.session.scalar(
        count_stmt
    ) or 0

    # Orden estable para paginación.
    stmt = (
        stmt
        .order_by(
            Event.starts_at.asc(),
            Event.id.asc(),
            InventoryReservation.id.asc()
        )
        .limit(per_page)
        .offset((page - 1) * per_page)
    )

    rows = db.session.execute(
        stmt
    ).all()

    items = [
        serialize_operation(
            reservation,
            event,
            item,
            dispatched,
            returned
        )
        for (
            reservation,
            event,
            item,
            dispatched,
            returned
        ) in rows
    ]

    return {
        "items": items,
        "total": int(total),
        "page": page,
        "per_page": per_page,
        "pages": (
            (total + per_page - 1) // per_page
        )
    }


def get_operations_summary(
    tenant_id,
    date_from=None,
    date_to=None
):
    """
    Resume todas las reservaciones del periodo.
    No aplica el límite de paginación.
    """

    stmt = build_operations_query(
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to
    )

    rows = db.session.execute(
        stmt
    ).all()

    summary = {
        "reservations": 0,
        "quantity_reserved": 0,
        "quantity_dispatched": 0,
        "quantity_returned": 0,
        "quantity_pending_dispatch": 0,
        "quantity_outstanding": 0,
        "overdue_reservations": 0
    }

    for (
        reservation,
        event,
        item,
        dispatched,
        returned
    ) in rows:

        operation = serialize_operation(
            reservation,
            event,
            item,
            dispatched,
            returned
        )

        summary["reservations"] += 1

        for field in (
            "quantity_reserved",
            "quantity_dispatched",
            "quantity_returned",
            "quantity_pending_dispatch",
            "quantity_outstanding"
        ):
            summary[field] += operation[field]

        if operation["is_overdue"]:
            summary["overdue_reservations"] += 1

    return summary
