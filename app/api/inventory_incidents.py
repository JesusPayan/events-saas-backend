from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, request, jsonify, g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect

from app.extensions import db
from app.models.inventory_incident import InventoryIncident
from app.models.inventory_incident_charge import InventoryIncidentCharge
from app.models.inventory_capacity_alert import InventoryCapacityAlert
from app.models.inventory_reconciliation_audit import (
    InventoryReconciliationAudit,
)
from app.security import tenant_permission
from app.services.inventory_incidents import (
    create_incident,
    IncidentError,
)
from app.services.inventory_reconciliation import (
    reconcile_incident,
    ReconciliationError,
)

bp = Blueprint("inventory_incidents", __name__)



@bp.post("/inventory/incidents/<int:incident_id>/reconcile")
@tenant_permission("inventory.adjust")
def reconcile_inventory_incident(incident_id):
    tenant_id = g.tenant_id
    user_id = g.user.id

    # Validar el cuerpo antes de ejecutar lógica de negocio.
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({
            "error": "invalid_json"
        }), 400

    try:
        result = reconcile_incident(
            tenant_id=tenant_id,
            incident_id=incident_id,
            user_id=user_id,
            payload=payload,
        )

        return jsonify(result), 200

    except ReconciliationError as exc:
        db.session.rollback()

        return jsonify({
            "error": exc.code,
        }), exc.status

    except IntegrityError as exc:
        db.session.rollback()

        original_error = getattr(exc, "orig", None)
        mysql_error_code = None

        if original_error is not None:
            args = getattr(original_error, "args", ())

            if args:
                mysql_error_code = args[0]

        duplicate_adjustment = (
            mysql_error_code == 1062
            and "uq_adjustment_incident" in str(original_error)
        )

        if duplicate_adjustment:
            return jsonify({
                "error": "incident_already_adjusted",
                "message": (
                    "La incidencia ya fue conciliada "
                    "por otra solicitud concurrente."
                ),
            }), 409

        # No ocultar otros errores de integridad.
        raise


    
    
@bp.get("/inventory/incidents")
@tenant_permission("inventory.read")
def list_incidents():

    query = (
        select(InventoryIncident)
        .where(InventoryIncident.tenant_id == g.tenant_id)
        .order_by(
            InventoryIncident.created_at.desc(),
            InventoryIncident.id.desc()
        )
    )

    reservation_id = request.args.get(
        "reservation_id",
        type=int
    )

    if reservation_id is not None:
        if reservation_id <= 0:
            return jsonify(error="invalid_reservation_id"), 400

        query = query.where(
            InventoryIncident.reservation_id == reservation_id
        )

    incidents = db.session.scalars(
        query.limit(100)
    ).all()

    return jsonify({
        "items": [incident.to_dict() for incident in incidents]
    }), 200


@bp.get("/inventory/incidents/<int:incident_id>")
@tenant_permission("inventory.read")
def get_incident(incident_id):

    incident = db.session.scalar(
        select(InventoryIncident).where(
            InventoryIncident.id == incident_id,
            InventoryIncident.tenant_id == g.tenant_id
        )
    )

    if incident is None:
        return jsonify(error="incident_not_found"), 404

    return jsonify(incident.to_dict()), 200


@bp.post("/inventory/incidents")
@tenant_permission("inventory.update")
def register_incident():

    try:
        incident = create_incident(
            tenant_id=g.tenant_id,
            user_id=g.user.id,
            data=request.get_json(silent=True)
        )

        return jsonify(incident), 201

    except IncidentError as exc:
        return jsonify(error=exc.code), exc.status
@bp.get("/inventory/incidents/<int:incident_id>/charges")
@tenant_permission("inventory.read")
def list_incident_charges(incident_id):

    incident = db.session.scalar(
        select(InventoryIncident).where(
            InventoryIncident.id == incident_id,
            InventoryIncident.tenant_id == g.tenant_id
        )
    )

    if incident is None:
        return jsonify(error="incident_not_found"), 404

    charges = db.session.scalars(
        select(InventoryIncidentCharge).where(
            InventoryIncidentCharge.tenant_id == g.tenant_id,
            InventoryIncidentCharge.incident_id == incident_id
        )
    ).all()

    return jsonify({
        "items": [charge.to_dict() for charge in charges]
    }), 200

def serialize_record(record):
    result = {}

    for column in inspect(record).mapper.column_attrs:
        value = getattr(record, column.key)

        if isinstance(value, Decimal):
            value = float(value)

        elif isinstance(value, (datetime, date)):
            value = value.isoformat()

        result[column.key] = value

    return result

@bp.get("/inventory/capacity-alerts")
@tenant_permission("inventory.read")
def list_capacity_alerts():

    query = select(InventoryCapacityAlert).where(
        InventoryCapacityAlert.tenant_id == g.tenant_id
    )

    item_id = request.args.get("item_id", type=int)

    if item_id is not None:
        if item_id <= 0:
            return jsonify(error="invalid_item_id"), 400

        query = query.where(
            InventoryCapacityAlert.inventory_item_id == item_id
        )

    alerts = db.session.scalars(
        query.order_by(
            InventoryCapacityAlert.id.desc()
        ).limit(100)
    ).all()

    return jsonify({
        "items": [
            serialize_record(alert)
            for alert in alerts
        ]
    }), 200

@bp.get("/inventory/reconciliation-audits")
@tenant_permission("inventory.read")
def list_reconciliation_audits():

    query = select(InventoryReconciliationAudit).where(
        InventoryReconciliationAudit.tenant_id == g.tenant_id
    )

    item_id = request.args.get("item_id", type=int)

    if item_id is not None:
        if item_id <= 0:
            return jsonify(error="invalid_item_id"), 400

        query = query.where(
            InventoryReconciliationAudit.inventory_item_id == item_id
        )

    audits = db.session.scalars(
        query.order_by(
            InventoryReconciliationAudit.id.desc()
        ).limit(100)
    ).all()

    return jsonify({
        "items": [
            serialize_record(audit)
            for audit in audits
        ]
    }), 200