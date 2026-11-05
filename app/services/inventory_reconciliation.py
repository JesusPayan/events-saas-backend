"""Conciliación de incidencias con déficit controlado (Sprint 4.5.2).

Requiere los modelos inventory_capacity_alert e inventory_reconciliation_audit,
y el servicio inventory_capacity_control definidos en este sprint.
"""
from decimal import Decimal, InvalidOperation

from flask import current_app
from sqlalchemy import select, func
from datetime import date, datetime
from decimal import Decimal
from app.extensions import db
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_incident import InventoryIncident
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_incident_charge import InventoryIncidentCharge
from app.models.inventory_reconciliation_audit import InventoryReconciliationAudit
from app.services.inventory_movements import get_movement_summary
from app.services.inventory_capacity_control import (
    get_item_capacity,
    synchronize_capacity_alerts,
)
from sqlalchemy.exc import OperationalError

MAX_MONEY = Decimal("9999999999.99")


class ReconciliationError(Exception):
    def __init__(self, code, status=409):
        self.code = code
        self.status = status
        super().__init__(code)


def parse_unit_cost(raw_cost):
    if raw_cost is None:
        raise ReconciliationError("unit_cost_required", 400)
    if isinstance(raw_cost, bool):
        raise ReconciliationError("invalid_unit_cost", 400)
    try:
        value = Decimal(str(raw_cost))
        if not value.is_finite() or value.as_tuple().exponent < -2:
            raise ValueError("invalid_precision")
        if value < 0 or value > MAX_MONEY:
            raise ValueError("out_of_range")
        return value.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ReconciliationError("invalid_unit_cost", 400)


def reconcile_incident(tenant_id, incident_id, user_id, payload):
    if not isinstance(payload, dict):
        raise ReconciliationError("invalid_json", 400)

    accept_deficit = payload.get("accept_deficit", False)
    if not isinstance(accept_deficit, bool):
        raise ReconciliationError("invalid_accept_deficit", 400)

    try:
        # Lectura inicial; los bloqueos siguen el orden artículo -> reserva -> incidencia.
        incident_ref = db.session.scalar(
            select(InventoryIncident).where(
                InventoryIncident.id == incident_id,
                InventoryIncident.tenant_id == tenant_id,
            )
        )
        if incident_ref is None:
            raise ReconciliationError("incident_not_found", 404)

        item = db.session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == incident_ref.inventory_item_id,
                InventoryItem.tenant_id == tenant_id,
            ).with_for_update()
        )
        if item is None:
            raise ReconciliationError("item_not_found", 404)

        reservation = db.session.scalar(
            select(InventoryReservation).where(
                InventoryReservation.id == incident_ref.reservation_id,
                InventoryReservation.tenant_id == tenant_id,
                InventoryReservation.inventory_item_id == item.id,
            ).with_for_update()
        )
        if reservation is None:
            raise ReconciliationError("reservation_not_found", 404)

        incident = db.session.scalar(
            select(InventoryIncident).where(
                InventoryIncident.id == incident_id,
                InventoryIncident.tenant_id == tenant_id,
                InventoryIncident.reservation_id == reservation.id,
                InventoryIncident.inventory_item_id == item.id,
            ).with_for_update()
        )
        if incident is None:
            raise ReconciliationError("incident_not_found", 404)
        if incident.status not in ("reported", "assessed"):
            raise ReconciliationError("incident_not_reconcilable")

        existing = db.session.scalar(
            select(InventoryAdjustment.id).where(
                InventoryAdjustment.tenant_id == tenant_id,
                InventoryAdjustment.incident_id == incident.id,
            )
        )
        if existing is not None:
            raise ReconciliationError("incident_already_adjusted")

        summary = get_movement_summary(tenant_id, reservation.id)
        returned = int(summary["quantity_returned"])
        administrative_outstanding = int(summary["quantity_administrative_outstanding"])

        previous_quarantine = int(db.session.scalar(
            select(func.coalesce(func.sum(InventoryAdjustment.quantity), 0))
            .join(
                InventoryIncident,
                (InventoryIncident.id == InventoryAdjustment.incident_id)
                & (InventoryIncident.tenant_id == InventoryAdjustment.tenant_id),
            )
            .where(
                InventoryAdjustment.tenant_id == tenant_id,
                InventoryIncident.reservation_id == reservation.id,
                InventoryAdjustment.adjustment_type == "quarantine",
            )
        ) or 0)

        quantity = int(incident.quantity)
        if quantity <= 0:
            raise ReconciliationError("invalid_incident_quantity", 400)

        total = int(item.quantity_total or 0)
        unavailable = int(item.quantity_unavailable or 0)

        if incident.incident_type in ("lost", "missing"):
            if quantity > administrative_outstanding:
                raise ReconciliationError("loss_exceeds_outstanding")
            if total - quantity < unavailable:
                raise ReconciliationError("stock_below_quarantined")
            new_total = total - quantity
            new_unavailable = unavailable
            adjustment_type = "loss"
        elif incident.incident_type == "damaged":
            if quantity > returned - previous_quarantine:
                raise ReconciliationError("damage_exceeds_returned")
            if unavailable + quantity > total:
                raise ReconciliationError("quarantine_exceeds_stock")
            new_total = total
            new_unavailable = unavailable + quantity
            adjustment_type = "quarantine"
        else:
            raise ReconciliationError("invalid_incident_type", 400)

        # La capacidad se calcula ANTES de modificar el artículo.
        capacity_before = get_item_capacity(tenant_id, item.id)
        if capacity_before is None:
            raise ReconciliationError("item_not_found", 404)
        usable_before = total - unavailable
        usable_after = new_total - new_unavailable
        max_reserved = int(capacity_before["max_reserved"])
        shortage_after = max(0, max_reserved - usable_after)

        current_app.logger.info(
            "Inventory reconciliation: tenant=%s item=%s incident=%s "
            "total=%s unavailable=%s new_total=%s new_unavailable=%s "
            "rentable_after=%s max_reserved=%s shortage_after=%s accept_deficit=%s",
            tenant_id, item.id, incident.id, total, unavailable,
            new_total, new_unavailable, usable_after, max_reserved,
            shortage_after, accept_deficit,
        )

        if shortage_after > 0 and not accept_deficit:
            raise ReconciliationError("inventory_capacity_conflict", 409)

        raw_cost = payload.get("unit_cost")
        if raw_cost is None:
            raw_cost = incident.unit_cost
        if raw_cost is None:
            raw_cost = item.replacement_cost
        unit_cost = parse_unit_cost(raw_cost)
        total_cost = unit_cost * quantity
        if total_cost > MAX_MONEY:
            raise ReconciliationError("total_cost_out_of_range", 400)

        item.quantity_total = new_total
        item.quantity_unavailable = new_unavailable
        incident.unit_cost = unit_cost
        incident.total_cost = total_cost
        incident.status = "resolved"

        adjustment = InventoryAdjustment(
            tenant_id=tenant_id, incident_id=incident.id,
            inventory_item_id=item.id, adjustment_type=adjustment_type,
            quantity=quantity, reason=incident.description, created_by=user_id,
        )
        charge = InventoryIncidentCharge(
            tenant_id=tenant_id, incident_id=incident.id,
            event_id=reservation.event_id, amount=total_cost,
            currency="MXN", status="pending",
            description=incident.description, created_by=user_id,
        )
        audit = InventoryReconciliationAudit(
            tenant_id=tenant_id, incident_id=incident.id,
            inventory_item_id=item.id, adjustment_type=adjustment_type,
            quantity=quantity, quantity_total_before=total,
            quantity_total_after=new_total, unavailable_before=unavailable,
            unavailable_after=new_unavailable, capacity_before=usable_before,
            capacity_after=usable_after, max_reserved=max_reserved,
            shortage_after=shortage_after, unit_cost=unit_cost,
            total_cost=total_cost,
            accepted_deficit=bool(shortage_after > 0 and accept_deficit),
            reason=incident.description, created_by=user_id,
        )
        
        db.session.add_all([adjustment, charge, audit])
        db.session.flush()

        # Sincronizar alertas dentro de la misma transacción.
        capacity_result = synchronize_capacity_alerts(
            tenant_id=tenant_id,
            item_id=item.id,
            source_type="reconciliation",
            source_id=incident.id,
            created_by=user_id,
        )

        db.session.flush()

        result = {
            "incident": serialize_model(incident),
            "adjustment": serialize_model(adjustment),
            "charge": serialize_model(charge),
            "inventory": serialize_model(item),
            "audit": serialize_model(audit),
            "capacity": capacity_result,
            "quantity_unresolved": max(
                0,
                administrative_outstanding
                - (quantity if adjustment_type == "loss" else 0),
            ),
        }

        db.session.commit()
        return result

    except OperationalError as exc:
        db.session.rollback()

        mysql_code = (
            exc.orig.args[0]
            if getattr(exc, "orig", None)
            and getattr(exc.orig, "args", None)
            else None
        )

        if mysql_code in (1205, 1213):
            current_app.logger.warning(
                "Inventory reconciliation concurrency conflict: "
                "tenant=%s incident=%s mysql_code=%s",
                tenant_id,
                incident_id,
                mysql_code,
            )
            raise ReconciliationError(
                "inventory_concurrency_conflict",
                409,
            ) from exc

        current_app.logger.exception(
            "Inventory reconciliation database error: "
            "tenant=%s incident=%s",
            tenant_id,
            incident_id,
        )
        raise

    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Inventory reconciliation failed: "
            "tenant=%s incident=%s",
            tenant_id,
            incident_id,
        )
        raise


def serialize_model(instance):
    result = {}

    for column in instance.__table__.columns:
        value = getattr(instance, column.name)

        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()

        result[column.name] = value

    return result

