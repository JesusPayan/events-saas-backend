
from unittest import result


from flask import Blueprint, request, jsonify, current_app
from app.extensions import db
from app.models.contract_signature import ContractSignature
from app.services.contract_signature_receipt_email import (
    send_signature_receipt
)
from app.services.contract_signing_service import (
    register_contract_signature,
    ContractSigningError,
)

bp = Blueprint("contract_signing", __name__)


@bp.post("/signatures/sign")
def sign_contract():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(
            error="invalid_json",
            message="Se requiere un objeto JSON.",
        ), 400

    try:
        result = register_contract_signature(
            token=data.get("token"),
            signature_data=data.get("signature_data"),
            consent_accepted=data.get("consent_accepted"),
            signer_name=data.get("signer_name"),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        email_sent = False

        try:
            signature = db.session.get(
                ContractSignature,
                result["signature_id"]
            )

            if signature is None:
                raise RuntimeError(
                    "No se encontró la firma registrada"
                )

            send_signature_receipt(
                tenant_id=signature.tenant_id,
                request_id=result["request_id"]
            )

            email_sent = True

        except Exception:
            current_app.logger.exception(
                "Firma registrada, pero falló el envío "
                "del comprobante"
            )

        result["receipt_email_sent"] = email_sent

        return jsonify(result), 201

    except ContractSigningError as exc:
        return jsonify(
            error=exc.code,
            message=exc.message,
        ), exc.status_code
