"""ROLES-01: API de plataforma (roles, organizaciones, auditoría, categorías),
promotores y accesos delegados de las organizaciones."""
import logging

from flask import Blueprint, current_app, g, jsonify, request

from app.branding import EMAIL_SIGNATURE, PRODUCT_NAME
from app.extensions import limiter
from app.security import authenticate, platform_permission, tenant_permission
from app.services.email_service import EmailDeliveryError, send_email
from app.services import catalog_service, platform_service as svc
from app.services.catalog_service import CatalogError
from app.services.platform_service import PlatformError

bp = Blueprint("platform", __name__)
logger = logging.getLogger(__name__)

ROLE_MANAGERS = ("platform.roles.manage_admins", "platform.roles.manage_promoters")


def _error(exc):
    return jsonify(error=exc.code, **exc.extra), exc.status


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise PlatformError("invalid_json", 400)
    return body


def _only(body, allowed, required=()):
    unknown = set(body) - set(allowed)
    if unknown:
        raise PlatformError("invalid_fields", 422, fields=sorted(unknown))
    missing = [f for f in required if f not in body]
    if missing:
        raise PlatformError("missing_fields", 422, fields=missing)


def _page():
    page = request.args.get("page", 1, type=int) or 1
    per_page = min(max(request.args.get("per_page", 20, type=int) or 20, 1), 100)
    return max(page, 1), per_page


def _frontend(path):
    return current_app.config.get("FRONTEND_PUBLIC_URL", "").rstrip("/") + path


def _send(to_email, subject, body):
    try:
        send_email(to_email=to_email, subject=subject, text_body=f"{body}\n\n{EMAIL_SIGNATURE}")
        return True
    except EmailDeliveryError:
        logger.warning("No se pudo enviar el correo: %s", subject)
        return False


# ----------------------------------------------------------------------------
# Plataforma: identidad y roles
# ----------------------------------------------------------------------------

@bp.get("/platform/me")
@authenticate
def platform_me():
    roles = sorted(svc.active_roles(g.user.id))
    return jsonify(roles=roles, permissions=sorted(svc.platform_permissions(g.user.id)),
                   role_labels={r: svc.ROLE_LABELS.get(r, r) for r in roles}), 200


@bp.get("/platform/roles")
@platform_permission(*ROLE_MANAGERS)
def list_roles():
    return jsonify(items=svc.list_assignments(), invitations=svc.list_platform_invitations(),
                   assignable=[r for r, p in (("platform_admin", "platform.roles.manage_admins"),
                                              ("promoter", "platform.roles.manage_promoters"))
                               if p in g.platform_permissions],
                   can_transfer_owner="platform.roles.transfer_owner" in g.platform_permissions), 200


@bp.post("/platform/roles")
@platform_permission(*ROLE_MANAGERS)
def grant_role():
    try:
        body = _body()
        _only(body, {"email", "role"}, required=("email", "role"))
        row, invitation = svc.grant_role(g.user.id, g.platform_permissions, body["email"], body["role"])
    except PlatformError as exc:
        return _error(exc)
    if row is not None:
        return jsonify(assignment=svc.assignment_dict(row), invited=False), 201
    inv, token = invitation
    url = _frontend(f"/platform-invite#token={token}")
    sent = _send(inv.email, f"Te invitaron a {PRODUCT_NAME}",
                 f"Hola,\n\nTe invitaron como {svc.ROLE_LABELS.get(inv.role_key)} en {PRODUCT_NAME}.\n\n"
                 f"Crea tu cuenta o entra con la tuya aquí (vence el {inv.expires_at:%d/%m/%Y}):\n{url}")
    return jsonify(invited=True, invitation_id=inv.id, invite_url=url, email_sent=sent), 201


@bp.post("/platform/roles/<int:assignment_id>/revoke")
@platform_permission(*ROLE_MANAGERS)
def revoke_role(assignment_id):
    try:
        row = svc.revoke_role(g.user.id, g.platform_permissions, assignment_id)
    except PlatformError as exc:
        return _error(exc)
    return jsonify(assignment=svc.assignment_dict(row)), 200


@bp.post("/platform/invitations/<int:invitation_id>/revoke")
@platform_permission(*ROLE_MANAGERS)
def revoke_platform_invitation(invitation_id):
    try:
        svc.revoke_platform_invitation(g.user.id, g.platform_permissions, invitation_id)
    except PlatformError as exc:
        return _error(exc)
    return jsonify(revoked=True), 200


@bp.post("/platform/owner/transfer")
@platform_permission("platform.roles.transfer_owner")
def transfer_owner():
    try:
        body = _body()
        _only(body, {"email", "keep_admin"}, required=("email",))
        keep_admin = body.get("keep_admin", True)
        if not isinstance(keep_admin, bool):
            raise PlatformError("invalid_keep_admin", 422)
        target = svc.transfer_ownership(g.user.id, body["email"], keep_admin=keep_admin)
    except PlatformError as exc:
        return _error(exc)
    return jsonify(transferred=True, new_owner_email=target.email), 200


@bp.post("/platform/invitations/lookup")
@limiter.limit("30 per hour")
def lookup_platform_invitation():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(svc.lookup_platform_invitation(body.get("token"))), 200
    except PlatformError as exc:
        return _error(exc)


@bp.post("/platform/invitations/accept")
@limiter.limit("10 per hour")
def accept_platform_invitation():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="invalid_json"), 400
    try:
        return jsonify(svc.accept_platform_invitation(body.get("token"), body.get("password"))), 200
    except PlatformError as exc:
        return _error(exc)


# ----------------------------------------------------------------------------
# Plataforma: organizaciones y auditoría
# ----------------------------------------------------------------------------

@bp.get("/platform/organizations")
@platform_permission("platform.orgs.manage")
def list_organizations():
    page, per_page = _page()
    result, items = svc.list_organizations(search=request.args.get("search"),
                                           status=request.args.get("status"), page=page, per_page=per_page)
    return jsonify(items=items, total=result.total, page=result.page, per_page=result.per_page), 200


@bp.post("/platform/organizations")
@platform_permission("platform.orgs.manage")
def create_organization():
    try:
        body = _body()
        _only(body, {"name", "slug", "owner_email"}, required=("name", "slug", "owner_email"))
        tenant, inv, token = svc.create_organization(g.user.id, body["name"], body["slug"], body["owner_email"])
    except PlatformError as exc:
        return _error(exc)
    url = _frontend(f"/invite#token={token}")
    sent = _send(inv.email, f"Tu empresa {tenant.name} ya está en {PRODUCT_NAME}",
                 f"Hola,\n\nDimos de alta a {tenant.name} en {PRODUCT_NAME} y quedaste como propietario.\n\n"
                 f"Activa tu acceso aquí (vence el {inv.expires_at:%d/%m/%Y}):\n{url}")
    return jsonify(organization=svc.organization_dict(tenant), invite_url=url, email_sent=sent), 201


@bp.patch("/platform/organizations/<int:tenant_id>/status")
@platform_permission("platform.orgs.manage")
def set_organization_status(tenant_id):
    try:
        body = _body()
        _only(body, {"status", "reason"}, required=("status",))
        tenant = svc.set_organization_status(g.user.id, tenant_id, body["status"], body.get("reason"))
    except PlatformError as exc:
        return _error(exc)
    return jsonify(organization=svc.organization_dict(tenant)), 200


@bp.get("/platform/audit")
@platform_permission("platform.audit.read")
def list_audit():
    page, per_page = _page()
    tenant_id = request.args.get("tenant_id", type=int)
    result, items = svc.list_audit(tenant_id=tenant_id, action=request.args.get("action"),
                                   page=page, per_page=per_page)
    return jsonify(items=items, total=result.total, page=result.page, per_page=result.per_page), 200


# ----------------------------------------------------------------------------
# Categorías del catálogo (globales)
# ----------------------------------------------------------------------------

@bp.get("/catalog/categories")
@authenticate
def list_categories():
    include_inactive = request.args.get("include_inactive") == "1" and bool(
        svc.platform_permissions(g.user.id) & {"platform.catalog.manage"})
    return jsonify(items=catalog_service.list_categories(include_inactive=include_inactive)), 200


@bp.post("/platform/catalog/categories")
@platform_permission("platform.catalog.manage")
def create_category():
    try:
        category = catalog_service.create_category(g.user.id, request.get_json(silent=True))
    except CatalogError as exc:
        return _error(exc)
    return jsonify(category=catalog_service.category_dict(category)), 201


@bp.patch("/platform/catalog/categories/<int:category_id>")
@platform_permission("platform.catalog.manage")
def update_category(category_id):
    try:
        category = catalog_service.update_category(g.user.id, category_id, request.get_json(silent=True))
    except CatalogError as exc:
        return _error(exc)
    return jsonify(category=catalog_service.category_dict(category)), 200


# ----------------------------------------------------------------------------
# Promotores (solo datos propios; nunca datos privados de las organizaciones)
# ----------------------------------------------------------------------------

@bp.get("/promoter/summary")
@platform_permission("promoter.referrals")
def promoter_summary():
    code = svc.referral_code(g.user.id)
    prospects = svc.list_prospects(g.user.id)
    referrals = svc.list_referrals(g.user.id)
    counts = {}
    for p in prospects:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return jsonify(code=code, link=svc.referral_link(code), prospects_by_status=counts,
                   referrals=len(referrals)), 200


@bp.get("/promoter/prospects")
@platform_permission("promoter.referrals")
def promoter_prospects():
    return jsonify(items=svc.list_prospects(g.user.id)), 200


@bp.post("/promoter/prospects")
@platform_permission("promoter.referrals")
def promoter_create_prospect():
    try:
        prospect = svc.create_prospect(g.user.id, request.get_json(silent=True))
    except PlatformError as exc:
        return _error(exc)
    return jsonify(prospect=svc.prospect_dict(prospect)), 201


@bp.patch("/promoter/prospects/<int:prospect_id>")
@platform_permission("promoter.referrals")
def promoter_update_prospect(prospect_id):
    try:
        prospect = svc.update_prospect(g.user.id, prospect_id, request.get_json(silent=True))
    except PlatformError as exc:
        return _error(exc)
    return jsonify(prospect=svc.prospect_dict(prospect)), 200


@bp.post("/promoter/prospects/<int:prospect_id>/invite")
@platform_permission("promoter.referrals")
@limiter.limit("60 per hour")
def promoter_invite_prospect(prospect_id):
    try:
        prospect = svc.mark_prospect_invited(g.user.id, prospect_id)
    except PlatformError as exc:
        return _error(exc)
    link = svc.referral_link(svc.referral_code(g.user.id))
    sent = _send(prospect.contact_email, f"Te invitamos a {PRODUCT_NAME}",
                 f"Hola{(' ' + prospect.contact_name) if prospect.contact_name else ''},\n\n"
                 f"Te invitamos a registrar {prospect.company_name} en {PRODUCT_NAME}.\n\n"
                 f"Crea tu cuenta aquí:\n{link}")
    return jsonify(prospect=svc.prospect_dict(prospect), link=link, email_sent=sent), 200


@bp.get("/promoter/referrals")
@platform_permission("promoter.referrals")
def promoter_referrals():
    return jsonify(items=svc.list_referrals(g.user.id)), 200


# ----------------------------------------------------------------------------
# Accesos delegados (los concede el administrador de la organización)
# ----------------------------------------------------------------------------

@bp.get("/access-grants")
@tenant_permission("members.read")
def list_access_grants():
    return jsonify(items=svc.list_grants(g.tenant_id), max_days=svc.MAX_GRANT_DAYS), 200


@bp.post("/access-grants")
@tenant_permission("members.manage")
def create_access_grant():
    try:
        body = _body()
        _only(body, {"email", "purpose", "days", "reason"}, required=("email", "purpose", "days"))
        grant = svc.create_grant(g.tenant_id, g.user.id, body["email"], body["purpose"], body["days"],
                                 body.get("reason"))
    except PlatformError as exc:
        return _error(exc)
    return jsonify(grant=svc.grant_dict(grant)), 201


@bp.post("/access-grants/<int:grant_id>/revoke")
@tenant_permission("members.manage")
def revoke_access_grant(grant_id):
    try:
        grant = svc.revoke_grant(g.tenant_id, g.user.id, grant_id)
    except PlatformError as exc:
        return _error(exc)
    return jsonify(grant=svc.grant_dict(grant)), 200
