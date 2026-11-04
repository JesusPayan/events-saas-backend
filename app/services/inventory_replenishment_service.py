
from sqlalchemy import select

from app.extensions import db
from app.models.inventory_item import InventoryItem
from app.models.inventory_replenishment import InventoryReplenishment
from app.services.inventory_capacity_control import (
    synchronize_capacity_alerts,
)


def replenish_inventory(
    tenant_id: int,
    item_id: int,
    quantity: int,
    reason: str,
    created_by: int,
    reference: str | None = None,
):
    """
    Ejecutar dentro de una transacción gestionada
    por el llamador.

    No ejecuta commit ni rollback.
    """

    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("invalid_replenishment_quantity")

    if quantity <= 0:
        raise ValueError("invalid_replenishment_quantity")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("replenishment_reason_required")

    if len(reason.strip()) > 2000:
        raise ValueError("replenishment_reason_too_long")

    if reference is not None:
        if not isinstance(reference, str):
            raise ValueError("invalid_replenishment_reference")

        reference = reference.strip() or None

        if reference and len(reference) > 100:
            raise ValueError("invalid_replenishment_reference")

    item = db.session.scalar(
        select(InventoryItem)
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.id == item_id
        )
        .with_for_update()
    )

    if item is None:
        raise ValueError("item_not_found")

    previous_quantity = item.quantity_total

    item.quantity_total += quantity

    replenishment = InventoryReplenishment(
        tenant_id=tenant_id,
        inventory_item_id=item_id,
        quantity=quantity,
        reason=reason.strip(),
        reference=reference,
        created_by=created_by,
    )

    db.session.add(replenishment)
    db.session.flush()

    capacity = synchronize_capacity_alerts(
    tenant_id=tenant_id,
    item_id=item_id,
    source_type="replenishment",
    source_id=replenishment.id,
    created_by=created_by
)

    return {
        "replenishment": replenishment.to_dict(),
        "previous_quantity_total": previous_quantity,
        "new_quantity_total": item.quantity_total,
        "capacity": capacity,
    }
