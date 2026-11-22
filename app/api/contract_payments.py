
from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError, DataError

from app.extensions import db
from app.security import tenant_permission
from app.services.contract_payment_service import (
    PaymentError,
    register_payment,
    confirm_payment,
    cancel_payment,
    get_balance,
    list_payments,
    list_payment_audits,
    serialize_payment,
    serialize_payment_audit,
)


bp = Blueprint("contract_payments", __name__)


def error_response(exc):
    return jsonify(
        error=exc.code,
        message=exc.message,
    ), exc.status_code


def database_error_response():
    db.session.rollback()
    return jsonify(
        error="payment_conflict_or_invalid_reference",
    ), 409


@bp.post("/contracts/<int:contract_id>/payments")
@tenant_permission("contracts.update")
def create_payment_endpoint(contract_id):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400

    allowed = {
        "amount",
        "payment_type",
        "payment_method",
        "reference",
        "notes",
    }

    if set(data) - allowed:
        return jsonify(error="unknown_fields"), 400

    required = {
        "amount",
        "payment_type",
        "payment_method",
    }

    if not required.issubset(data):
        return jsonify(error="missing_fields"), 400

    try:
        payment = register_payment(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
            user_id=g.user.id,
            amount=data["amount"],
            payment_type=data["payment_type"],
            payment_method=data["payment_method"],
            reference=data.get("reference"),
            notes=data.get("notes"),
        )

        return jsonify(serialize_payment(payment)), 201

    except PaymentError as exc:
        db.session.rollback()
        return error_response(exc)

    except (IntegrityError, DataError):
        return database_error_response()


@bp.get("/contracts/<int:contract_id>/payments")
@tenant_permission("contracts.read")
def list_payments_endpoint(contract_id):
    try:
        payments = list_payments(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
        )

        return jsonify({
            "items": [
                serialize_payment(payment)
                for payment in payments
            ],
            "total": len(payments),
        }), 200

    except PaymentError as exc:
        return error_response(exc)


@bp.get("/contracts/<int:contract_id>/payments/balance")
@tenant_permission("contracts.read")
def get_balance_endpoint(contract_id):
    try:
        balance = get_balance(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
        )

        return jsonify(balance), 200

    except PaymentError as exc:
        return error_response(exc)


@bp.patch(
    "/contracts/<int:contract_id>/payments/"
    "<int:payment_id>/confirm"
)
@tenant_permission("contracts.update")
def confirm_payment_endpoint(contract_id, payment_id):
    data = request.get_json(silent=True)

    if data is not None and (
        not isinstance(data, dict) or data
    ):
        return jsonify(error="invalid_fields"), 400

    try:
        payment = confirm_payment(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
            payment_id=payment_id,
            user_id=g.user.id,
        )

        return jsonify(serialize_payment(payment)), 200

    except PaymentError as exc:
        db.session.rollback()
        return error_response(exc)

    except (IntegrityError, DataError):
        return database_error_response()


@bp.patch(
    "/contracts/<int:contract_id>/payments/"
    "<int:payment_id>/cancel"
)
@tenant_permission("contracts.update")
def cancel_payment_endpoint(contract_id, payment_id):
    data = request.get_json(silent=True)

    if data is None:
        data = {}

    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400

    if set(data) - {"notes"}:
        return jsonify(error="unknown_fields"), 400

    try:
        payment = cancel_payment(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
            payment_id=payment_id,
            user_id=g.user.id,
            notes=data.get("notes"),
        )

        return jsonify(serialize_payment(payment)), 200

    except PaymentError as exc:
        db.session.rollback()
        return error_response(exc)

    except (IntegrityError, DataError):
        return database_error_response()


@bp.get(
    "/contracts/<int:contract_id>/payments/"
    "<int:payment_id>/audit"
)
@tenant_permission("contracts.read")
def payment_audit_endpoint(contract_id, payment_id):
    try:
        audits = list_payment_audits(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
            payment_id=payment_id,
        )

        return jsonify({
            "items": [
                serialize_payment_audit(audit)
                for audit in audits
            ],
            "total": len(audits),
        }), 200

    except PaymentError as exc:
        return error_response(exc)
