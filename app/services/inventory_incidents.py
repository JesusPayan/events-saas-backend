
from sqlalchemy import select, func

from app.extensions import db
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_incident import InventoryIncident
from app.services.inventory_movements import get_movement_summary


class IncidentError(Exception):
    def __init__(self, code, status=400):
        self.code = code
        self.status = status
        super().__init__(code)


def create_incident(tenant_id, user_id, data):
    if not isinstance(data, dict):
        raise IncidentError("invalid_json")

    reservation_id = data.get("reservation_id")
    quantity = data.get("quantity")
    incident_type = data.get("incident_type")
    description = data.get("description")

    if type(reservation_id) is not int or reservation_id <= 0:
        raise IncidentError("invalid_reservation_id")

    if type(quantity) is not int or quantity <= 0:
        raise IncidentError("invalid_quantity")

    if incident_type not in ("damaged", "lost", "missing"):
        raise IncidentError("invalid_incident_type")

    if not isinstance(description, str) or not description.strip():
        raise IncidentError("invalid_description")

    if len(description) > 2000:
        raise IncidentError("description_too_long")

    try:
        # Localizar reservación para identificar el artículo.
        reservation = db.session.scalar(
            select(InventoryReservation).where(
                InventoryReservation.id == reservation_id,
                InventoryReservation.tenant_id == tenant_id
            )
        )

        if reservation is None:
            raise IncidentError("reservation_not_found", 404)

        # Orden de bloqueo consistente con movimientos.
        item = db.session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == reservation.inventory_item_id,
                InventoryItem.tenant_id == tenant_id
            ).with_for_update()
        )

        if item is None:
            raise IncidentError("item_not_found", 404)

        reservation = db.session.scalar(
            select(InventoryReservation).where(
                InventoryReservation.id == reservation_id,
                InventoryReservation.tenant_id == tenant_id,
                InventoryReservation.inventory_item_id == item.id
            ).with_for_update()
        )

        if reservation is None:
            raise IncidentError("reservation_not_found", 404)

        summary = get_movement_summary(
            tenant_id,
            reservation.id
        )

        dispatched = summary["quantity_dispatched"]

        if dispatched <= 0:
            raise IncidentError("nothing_dispatched", 409)

        # Excluir incidencias canceladas.
        already_reported = db.session.scalar(
            select(
                func.coalesce(
                    func.sum(InventoryIncident.quantity),
                    0
                )
            ).where(
                InventoryIncident.tenant_id == tenant_id,
                InventoryIncident.reservation_id == reservation.id,
                InventoryIncident.status != "cancelled"
            )
        )

        remaining = dispatched - int(already_reported or 0)

        if quantity > remaining:
            raise IncidentError(
                "incident_exceeds_dispatched",
                409
            )

        incident = InventoryIncident(
            tenant_id=tenant_id,
            reservation_id=reservation.id,
            inventory_item_id=item.id,
            incident_type=incident_type,
            quantity=quantity,
            description=description.strip(),
            status="reported",
            reported_by=user_id
        )

        db.session.add(incident)
        db.session.flush()

        result = incident.to_dict()
        db.session.commit()

        return result

    except Exception:
        db.session.rollback()
        raise
