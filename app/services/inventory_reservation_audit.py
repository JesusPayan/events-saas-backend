
from app.extensions import db
from app.models.inventory_reservation_audit import (
    InventoryReservationAudit,
)


def audit_reservation(
    *,
    tenant_id,
    reservation_id,
    action,
    changed_by,
    previous_quantity=None,
    new_quantity=None,
    previous_status=None,
    new_status,
):
    audit = InventoryReservationAudit(
        tenant_id=tenant_id,
        reservation_id=reservation_id,
        action=action,
        previous_quantity=previous_quantity,
        new_quantity=new_quantity,
        previous_status=previous_status,
        new_status=new_status,
        changed_by=changed_by,
    )

    db.session.add(audit)
    return audit
