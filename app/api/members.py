"""AUTH-02: gestión de miembros e invitaciones de la empresa."""
import logging

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import select

from app.branding import EMAIL_SIGNATURE, PRODUCT_NAME
from app.extensions import db, limiter
from app.models import Tenant
from app.models.identity import TenantInvitation
from app.security import tenant_permission
from app.services.email_service import EmailDeliveryError, send_email
from app.services.members_service import (
    MembersError, accept_invitation, change_role, create_invitation, invitation_dict,
    lookup_invitation, revoke_invitation, set_member_status,
)

bp = Blueprint("members", __name__)
logger = logging.getLogger(__name__)

ROLE_NAMES = {"owner": "Propietario", "admin": "Administrador", "staff": "Operativo", "viewer": "Solo lectura",
              "provider": "Proveedor"}


def _error(exc):
    return jsonify(error=exc.code, **exc.extra), exc.status


def _invite_url(token):
    base = current_app.config.get("FRONTEND_PUBLIC_URL", "").rstrip("/")
    # El token va en el fragmento (#): el navegador nunca lo envía al servidor ni queda en logs.
    return f"{base}/invite#token={token}"


@bp.get("/invitations")
@tenant_permission("members.read")
def list_invitations():
    rows = db.session.scalars(select(TenantInvitation).where(
        TenantInvitation.tenant_id == g.tenant_id, TenantInvitation.status == "pending"
    ).order_by(TenantInvitation.id.desc())).all()
    return jsonify(items=[invitation_dict(i) for i in rows]), 200


@bp.post("/invitations")
@tenant_permission("members.manage")
def invite():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not {"email", "role"} <= set(body) <= {"email", "role", "provider_id"}:
        return jsonify(error="invalid_fields"), 422
    try:
        inv, token = create_invitation(g.tenant_id, g.user.id, body["email"], body["role"],
                                       body.get("provider_id"))
    except MembersError as exc:
        db.session.rollback()
        return _error(exc)
    url = _invite_url(token)
    tenant = db.session.get(Tenant, g.tenant_id)
    email_sent = True
    try:
        send_email(
            to_email=inv.email,
            subject=f"Te invitaron a {tenant.name} en {PRODUCT_NAME}",
            text_body=(
                f"Hola,\n\n{g.user.email} te invitó a unirte a {tenant.name} en {PRODUCT_NAME} "
                f"con el rol {ROLE_NAMES.get(inv.role_key, inv.role_key)}.\n\n"
                f"Acepta la invitación aquí (vence el {inv.expires_at:%d/%m/%Y}):\n{url}\n\n"
                "Si no esperabas este correo, puedes ignorarlo.\n\n"
                f"{EMAIL_SIGNATURE}"
            ),
        )
    except EmailDeliveryError:
        email_sent = False
        logger.warning("No se pudo enviar la invitación por correo: invitation_id=%s", inv.id)
    # El enlace se devuelve solo a quien invita, para compartirlo si el correo falla.
    return jsonify(invitation=invitation_dict(inv), invite_url=url, email_sent=email_sent), 201


@bp.post("/invitations/<int:invitation_id>/revoke")
@tenant_permission("members.manage")
def revoke(invitation_id):
    try:
        return jsonify(invitation=invitation_dict(revoke_invitation(g.tenant_id, invitation_id))), 200
    except MembersError as exc:
        db.session.rollback()
        return _error(exc)


@bp.post("/invitations/lookup")
@limiter.limit("30 per hour")
def lookup():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(lookup_invitation(body.get("token"))), 200
    except MembersError as exc:
        return _error(exc)


@bp.post("/invitations/accept")
@limiter.limit("10 per hour")
def accept():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="invalid_json"), 400
    try:
        return jsonify(accept_invitation(body.get("token"), body.get("password"))), 200
    except MembersError as exc:
        return _error(exc)


@bp.patch("/memberships/<int:membership_id>")
@tenant_permission("members.manage")
def update_role(membership_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not {"role"} <= set(body) <= {"role", "provider_id"}:
        return jsonify(error="invalid_fields"), 422
    try:
        member = change_role(g.tenant_id, membership_id, g.user.id, body["role"], body.get("provider_id"))
        return jsonify(id=member.id, role=body["role"], status=member.status,
                       provider_id=member.provider_id), 200
    except MembersError as exc:
        db.session.rollback()
        return _error(exc)


@bp.post("/memberships/<int:membership_id>/deactivate")
@tenant_permission("members.manage")
def deactivate(membership_id):
    try:
        member = set_member_status(g.tenant_id, membership_id, g.user.id, False)
        return jsonify(id=member.id, status=member.status), 200
    except MembersError as exc:
        db.session.rollback()
        return _error(exc)


@bp.post("/memberships/<int:membership_id>/activate")
@tenant_permission("members.manage")
def activate(membership_id):
    try:
        member = set_member_status(g.tenant_id, membership_id, g.user.id, True)
        return jsonify(id=member.id, status=member.status), 200
    except MembersError as exc:
        db.session.rollback()
        return _error(exc)
