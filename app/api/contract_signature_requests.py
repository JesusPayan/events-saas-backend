
from flask import Blueprint, jsonify, request, g, current_app
from urllib.parse import quote

from app.security import tenant_permission
from app.extensions import db

from app.services.contract_signature_request_service import (
    create_signature_request,
    SignatureRequestError,
)

from app.services.email_service import send_email


bp = Blueprint(
    "contract_signature_requests",
    __name__,
)


@bp.post("/contracts/<int:contract_id>/signature-requests")
@tenant_permission("contracts.update")
def create_invitation(contract_id):
    data = request.get_json(silent=True) or {}

    try:
        invitation, token = create_signature_request(
            tenant_id=g.tenant_id,
            contract_id=contract_id,
            document_id=data.get("document_id"),
            signer_role=data.get("signer_role"),
            signer_name=data.get("signer_name"),
            signer_email=data.get("signer_email"),
            user_id=g.user.id,
        )

        frontend_url = current_app.config.get(
            "FRONTEND_PUBLIC_URL"
        )

        if not frontend_url:
            raise RuntimeError(
                "FRONTEND_PUBLIC_URL no configurada"
            )

        signing_url = (
            f"{frontend_url.rstrip('/')}/sign/"
            f"{quote(token, safe='')}"
        )

        try:
            send_email(
                to_email=invitation.signer_email,
                subject="Invitación para firmar contrato",
                text_body=(
                    f"Hola {invitation.signer_name},\n\n"
                    "Has recibido una invitación para "
                    "firmar electrónicamente un contrato.\n\n"
                    f"Accede aquí:\n{signing_url}\n\n"
                    "Este enlace es personal y confidencial. "
                    "No lo compartas.\n\n"
                    "Eventos SaaS"
                ),
            )

        except Exception:
            # El servicio ya guardó la invitación.
            # Revocarla impide utilizar un enlace
            # cuyo envío no pudo confirmarse.
            from datetime import datetime, timezone

            invitation.status = "revoked"
            invitation.revoked_at = datetime.now(
                timezone.utc
            ).replace(tzinfo=None)

            db.session.commit()

            current_app.logger.exception(
                "No se pudo enviar la invitación %s",
                invitation.id,
            )

            return jsonify(
                error="invitation_delivery_failed",
                message="No se pudo enviar la invitación.",
            ), 502

        return jsonify(
            id=invitation.id,
            contract_id=invitation.contract_id,
            document_id=invitation.document_id,
            signer_email=invitation.signer_email,
            status=invitation.status,
            message="Invitación enviada correctamente.",
        ), 201

    except SignatureRequestError as exc:
        return jsonify(
            error=exc.code,
            message=exc.message,
        ), exc.status_code
