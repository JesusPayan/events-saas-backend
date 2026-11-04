
from sqlalchemy import select, func

from app.extensions import db
from app.models.inventory_movement import InventoryMovement
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_incident import InventoryIncident


def get_movement_summary(tenant_id, reservation_id):

    # 1. Movimientos físicos originales.
    rows = db.session.execute(
        select(
            InventoryMovement.movement_type,
            func.sum(InventoryMovement.quantity)
        )
        .where(
            InventoryMovement.tenant_id == tenant_id,
            InventoryMovement.reservation_id == reservation_id
        )
        .group_by(InventoryMovement.movement_type)
    ).all()

    totals = dict(rows)

    dispatched = int(totals.get("dispatch") or 0)
    returned = int(totals.get("return") or 0)

    # 2. Pérdidas autorizadas y conciliadas.
    lost = int(
        db.session.scalar(
            select(
                func.coalesce(
                    func.sum(InventoryAdjustment.quantity),
                    0
                )
            )
            .join(
                InventoryIncident,
                (InventoryIncident.id ==
                 InventoryAdjustment.incident_id)
                &
                (InventoryIncident.tenant_id ==
                 InventoryAdjustment.tenant_id)
            )
            .where(
                InventoryAdjustment.tenant_id == tenant_id,
                InventoryIncident.reservation_id == reservation_id,
                InventoryAdjustment.adjustment_type == "loss",
                InventoryIncident.status == "resolved"
            )
        ) or 0
    )

    physical_outstanding = dispatched - returned

    administrative_outstanding = (
        physical_outstanding - lost
    )

    return {
        # Campos anteriores: se mantienen.
        "quantity_dispatched": dispatched,
        "quantity_returned": returned,
        "quantity_outstanding": physical_outstanding,

        # Campos nuevos.
        "quantity_lost": lost,
        "quantity_physical_outstanding": physical_outstanding,
        "quantity_administrative_outstanding": (
            administrative_outstanding
        ),
        "quantity_reconciled": returned + lost,
        "is_fully_reconciled": (
            administrative_outstanding == 0
            and physical_outstanding >= 0
        )
    }
