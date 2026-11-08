
from sqlalchemy import select, func, and_, or_

from app.extensions import db
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.services.inventory_reservations import (
    BLOCKING_STATUSES,
    validate_date_range,
)


def get_availability_report(
    tenant_id,
    starts_at,
    ends_at,
    category_id=None,
    item_id=None,
    search=None,
    page=1,
    per_page=20,
):
    validate_date_range(starts_at, ends_at)

    reserved_by_item = (
        select(
            InventoryReservation.inventory_item_id.label("item_id"),
            func.sum(InventoryReservation.quantity).label("reserved"),
        )
        .join(
            Event,
            and_(
                Event.id == InventoryReservation.event_id,
                Event.tenant_id == InventoryReservation.tenant_id,
            ),
        )
        .where(
            InventoryReservation.tenant_id == tenant_id,
            InventoryReservation.status.in_(BLOCKING_STATUSES),
            Event.status != "cancelled",
            Event.starts_at < ends_at,
            Event.ends_at > starts_at,
        )
        .group_by(InventoryReservation.inventory_item_id)
        .subquery()
    )

    stmt = (
        select(
            InventoryItem,
            func.coalesce(
                reserved_by_item.c.reserved, 0
            ).label("quantity_reserved"),
        )
        .outerjoin(
            reserved_by_item,
            reserved_by_item.c.item_id == InventoryItem.id,
        )
        .where(InventoryItem.tenant_id == tenant_id)
    )

    if category_id is not None:
        stmt = stmt.where(
            InventoryItem.category_id == category_id
        )

    if item_id is not None:
        stmt = stmt.where(InventoryItem.id == item_id)

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                InventoryItem.name.ilike(pattern),
                InventoryItem.sku.ilike(pattern),
            )
        )

    count_stmt = select(func.count()).select_from(
        stmt.order_by(None).subquery()
    )

    total = int(db.session.scalar(count_stmt) or 0)

    rows = db.session.execute(
        stmt.order_by(
            InventoryItem.name.asc(),
            InventoryItem.id.asc(),
        )
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    items = []

    for item, reserved_value in rows:
        total_quantity = int(item.quantity_total or 0)
        unavailable = int(item.quantity_unavailable or 0)
        rentable = max(total_quantity - unavailable, 0)
        reserved = int(reserved_value or 0)

        items.append({
            "inventory_item_id": item.id,
            "category_id": item.category_id,
            "sku": item.sku,
            "name": item.name,
            "unit": item.unit,
            "is_active": item.is_active,
            "quantity_total": total_quantity,
            "quantity_unavailable": unavailable,
            "quantity_rentable": rentable,
            "quantity_reserved": reserved,
            "quantity_available": max(rentable - reserved, 0),
            "inventory_shortage": max(reserved - rentable, 0),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }
