
from sqlalchemy import case, select, func, and_

from app.extensions import db
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_movement import InventoryMovement


def get_movement_report(
    tenant_id,
    date_from=None,
    date_to=None,
    event_id=None,
    item_id=None,
    movement_type=None,
    page=1,
    per_page=20,
):
    if (
        date_from is not None
        and date_to is not None
        and date_to <= date_from
    ):
        raise ValueError("invalid_date_range")

    filters = [
        InventoryMovement.tenant_id == tenant_id,
    ]

    if date_from is not None:
        filters.append(
            InventoryMovement.created_at >= date_from
        )

    if date_to is not None:
        filters.append(
            InventoryMovement.created_at < date_to
        )

    if event_id is not None:
        filters.append(
            InventoryReservation.event_id == event_id
        )

    if item_id is not None:
        filters.append(
            InventoryMovement.inventory_item_id == item_id
        )

    if movement_type is not None:
        if movement_type not in ("dispatch", "return"):
            raise ValueError("invalid_movement_type")

        filters.append(
            InventoryMovement.movement_type == movement_type
        )

    base = (
        select(
            InventoryMovement.id.label("movement_id"),
            InventoryMovement.reservation_id,
            InventoryMovement.inventory_item_id,
            InventoryReservation.event_id,
            InventoryItem.sku,
            InventoryItem.name.label("item_name"),
            InventoryMovement.movement_type,
            InventoryMovement.quantity,
            InventoryMovement.notes,
            InventoryMovement.created_by,
            InventoryMovement.created_at,
        )
        .join(
            InventoryReservation,
            and_(
                InventoryReservation.id
                == InventoryMovement.reservation_id,
                InventoryReservation.tenant_id
                == InventoryMovement.tenant_id,
            ),
        )
        .join(
            InventoryItem,
            and_(
                InventoryItem.id
                == InventoryMovement.inventory_item_id,
                InventoryItem.tenant_id
                == InventoryMovement.tenant_id,
            ),
        )
        .join(
            Event,
            and_(
                Event.id == InventoryReservation.event_id,
                Event.tenant_id
                == InventoryMovement.tenant_id,
            ),
        )
        .where(*filters)
    )

    movements = base.subquery()

    summary_row = db.session.execute(
        select(
            func.count().label("total"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            movements.c.movement_type == "dispatch",
                            movements.c.quantity,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("dispatched"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            movements.c.movement_type == "return",
                            movements.c.quantity,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("returned"),
        ).select_from(movements)
    ).one()

    total = int(summary_row.total)
    dispatched = int(summary_row.dispatched)
    returned = int(summary_row.returned)

    rows = db.session.execute(
        base.order_by(
            InventoryMovement.created_at.desc(),
            InventoryMovement.id.desc(),
        )
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).mappings().all()

    items = []

    for row in rows:
        item = dict(row)
        created_at = item["created_at"]

        item["created_at"] = (
            created_at.isoformat() + "Z"
            if created_at is not None
            else None
        )

        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "summary": {
            "quantity_dispatched": dispatched,
            "quantity_returned": returned,
            "quantity_outstanding": max(
                dispatched - returned, 0
            ),
        },
    }
