"""COM-02.1.10 API: invitaciones y OTP.

No registrar tokens, códigos OTP ni cuerpos de solicitudes en los logs.
La consulta pública de invitaciones se atiende exclusivamente desde
app.api.signature_read.invitation_details.
"""

from flask import Blueprint, request, jsonify, g

from app.security import tenant_permission
from app.services.signature_delivery_service import (
    SignatureDeliveryError,
    create_and_email_invitation,
    request_otp,
    verify_otp,
)

bp = Blueprint("signature_delivery", __name__)


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise SignatureDeliveryError(
            "invalid_json",
            "Se requiere un objeto JSON.",
        )
    return data


def fail(exc):
    return jsonify(error=exc.code, message=exc.message), exc.status


@bp.post("/contracts/<int:contract_id>/signature-requests")
@tenant_permission("contracts.update")
def create_invitation(contract_id):
    try:
        data = payload()
        inv = create_and_email_invitation(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
            document_id=data.get("document_id"),
            signer_role=data.get("signer_role"),
            signer_name=data.get("signer_name"),
            signer_email=data.get("signer_email"),
            created_by=g.user.id,
        )
        return jsonify(
            id=inv.id,
            contract_id=inv.contract_id,
            document_id=inv.document_id,
            status=inv.status,
            message="Invitación enviada.",
        ), 201
    except SignatureDeliveryError as exc:
        return fail(exc)


@bp.post("/signatures/otp/request")
def send_otp():
    try:
        data = payload()
        return jsonify(request_otp(data.get("token"))), 200
    except SignatureDeliveryError as exc:
        return fail(exc)


@bp.post("/signatures/otp/verify")
def confirm_otp():
    try:
        data = payload()
        return jsonify(verify_otp(data.get("token"), data.get("code"))), 200
    except SignatureDeliveryError as exc:
        return fail(exc)
