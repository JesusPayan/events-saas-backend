
from flask import Blueprint, request, jsonify, g
from sqlalchemy import select

from app.extensions import db
from app.security import tenant_permission

from app.models.inventory_incident_charge import (
    InventoryIncidentCharge
)
from app.models.inventory_charge_audit import (
    InventoryChargeAudit
)
from app.services.inventory_charges import (
    change_charge_status,
    ChargeError
)


bp = Blueprint("inventory_charges", __name__)


def execute_action(charge_id, action):
    try:
        result = change_charge_status(
            tenant_id=g.tenant_id,
            charge_id=charge_id,
            user_id=g.user.id,
            action=action,
            data=request.get_json(silent=True) or {}
        )

        return jsonify(result), 200

    except ChargeError as exc:
        return jsonify(error=exc.code), exc.status


@bp.get("/inventory/charges")
@tenant_permission("inventory.read")
def list_charges():
    query = (
        select(InventoryIncidentCharge)
        .where(
            InventoryIncidentCharge.tenant_id == g.tenant_id
        )
        .order_by(
            InventoryIncidentCharge.created_at.desc()
        )
        .limit(100)
    )

    charges = db.session.scalars(query).all()

    return jsonify({
        "items": [charge.to_dict() for charge in charges]
    }), 200


@bp.post("/inventory/charges/<int:charge_id>/approve")
@tenant_permission("inventory.charges.approve")
def approve_charge(charge_id):
    return execute_action(charge_id, "approve")


@bp.post("/inventory/charges/<int:charge_id>/waive")
@tenant_permission("inventory.charges.approve")
def waive_charge(charge_id):
    return execute_action(charge_id, "waive")


@bp.post("/inventory/charges/<int:charge_id>/pay")
@tenant_permission("inventory.charges.pay")
def pay_charge(charge_id):
    return execute_action(charge_id, "pay")


@bp.get("/inventory/charges/<int:charge_id>/audit")
@tenant_permission("inventory.read")
def charge_audit(charge_id):

    charge = db.session.scalar(
        select(InventoryIncidentCharge).where(
            InventoryIncidentCharge.id == charge_id,
            InventoryIncidentCharge.tenant_id == g.tenant_id
        )
    )

    if charge is None:
        return jsonify(error="charge_not_found"), 404

    audits = db.session.scalars(
        select(InventoryChargeAudit)
        .where(
            InventoryChargeAudit.tenant_id == g.tenant_id,
            InventoryChargeAudit.charge_id == charge_id
        )
        .order_by(InventoryChargeAudit.created_at)
    ).all()

    return jsonify({
        "items": [audit.to_dict() for audit in audits]
    }), 200
