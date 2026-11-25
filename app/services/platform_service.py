"""ROLES-01: roles de plataforma con alcance, auditoría, organizaciones,
accesos delegados y promotores.

Reglas principales:
- El dueño de plataforma gestiona administradores y promotores y puede transferir
  la propiedad. La plataforma nunca queda sin dueño.
- El administrador de plataforma gestiona organizaciones, incidencias y promotores.
  No puede asignar el rol de dueño ni el de administrador.
- El promotor solo ve sus prospectos y el avance de sus altas; nunca datos privados.
- Los roles reservados (soporte, finanzas, auditoría) existen en el modelo pero no
  se pueden asignar hasta definir sus permisos.
- Los usuarios en ``BILLING_OPERATOR_USER_IDS`` conservan sus capacidades previas
  (planes, suscripciones e incidencias) como compatibilidad.
"""
import hashlib
import re
import secrets
from datetime import timedelta

from flask import current_app, request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import Tenant
from app.models.identity import Membership, Role, TenantInvitation, User, now
from app.models.platform import (
    AuditEvent, PlatformInvitation, PlatformRoleAssignment, PromoterProspect,
    PromoterReferralCode, TenantAccessGrant, TenantReferral,
)

PLATFORM_ROLE_PERMISSIONS = {
    "platform_owner": frozenset({
        "platform.roles.manage_admins", "platform.roles.manage_promoters",
        "platform.roles.transfer_owner", "platform.plans.manage", "platform.orgs.manage",
        "platform.billing.operate", "platform.catalog.manage", "platform.audit.read",
    }),
    "platform_admin": frozenset({
        "platform.roles.manage_promoters", "platform.orgs.manage", "platform.billing.operate",
        "platform.catalog.manage", "platform.audit.read",
    }),
    "promoter": frozenset({"promoter.referrals"}),
    # Reservados: se habilitan cuando exista una necesidad concreta.
    "support": frozenset(),
    "finance": frozenset(),
    "auditor": frozenset(),
}
RESERVED_ROLES = frozenset({"support", "finance", "auditor"})
LEGACY_OPERATOR_PERMISSIONS = frozenset({
    "platform.plans.manage", "platform.billing.operate", "platform.audit.read",
})
ROLE_LABELS = {
    "platform_owner": "Dueño de plataforma", "platform_admin": "Administrador de plataforma",
    "promoter": "Promotor", "support": "Soporte", "finance": "Finanzas", "auditor": "Auditoría",
}
# Quién puede asignar o revocar cada rol.
_MANAGE_PERMISSION = {
    "platform_admin": "platform.roles.manage_admins",
    "promoter": "platform.roles.manage_promoters",
}
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,98}[a-z0-9])?")


class PlatformError(Exception):
    def __init__(self, code, status=400, **extra):
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


# ----------------------------------------------------------------------------
# Auditoría
# ----------------------------------------------------------------------------

def _client_ip():
    try:
        return (request.remote_addr or "")[:45] or None
    except RuntimeError:  # fuera de una petición (scripts)
        return None


def record_audit(actor_id, action, *, tenant_id=None, target_type=None, target_id=None,
                 details=None, commit=False):
    db.session.add(AuditEvent(
        actor_user_id=actor_id, action=action, scope_type="tenant" if tenant_id else "platform",
        tenant_id=tenant_id, target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details or None, ip_address=_client_ip(), created_at=now()))
    if commit:
        db.session.commit()


def audit_dict(event, emails=None):
    emails = emails or {}
    return {
        "id": event.id, "action": event.action, "scope_type": event.scope_type,
        "tenant_id": event.tenant_id, "actor_user_id": event.actor_user_id,
        "actor_email": emails.get(event.actor_user_id), "target_type": event.target_type,
        "target_id": event.target_id, "details": event.details,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def list_audit(*, tenant_id=None, action=None, page=1, per_page=50):
    query = select(AuditEvent).order_by(AuditEvent.id.desc())
    if tenant_id is not None:
        query = query.where(AuditEvent.tenant_id == tenant_id)
    if action:
        query = query.where(AuditEvent.action.like(f"{action}%"))
    result = db.paginate(query, page=page, per_page=per_page, error_out=False)
    emails = _emails({e.actor_user_id for e in result.items if e.actor_user_id})
    return result, [audit_dict(e, emails) for e in result.items]


def _emails(user_ids):
    if not user_ids:
        return {}
    return dict(db.session.execute(select(User.id, User.email).where(User.id.in_(user_ids))).all())


# ----------------------------------------------------------------------------
# Roles de plataforma
# ----------------------------------------------------------------------------

def active_roles(user_id):
    return set(db.session.scalars(select(PlatformRoleAssignment.role_key).where(
        PlatformRoleAssignment.user_id == user_id, PlatformRoleAssignment.status == "active")).all())


def platform_permissions(user_id):
    granted = set()
    for role in active_roles(user_id):
        granted |= PLATFORM_ROLE_PERMISSIONS.get(role, frozenset())
    legacy = current_app.config.get("BILLING_OPERATOR_USER_IDS", ())
    if isinstance(legacy, (tuple, list, set, frozenset)) and not isinstance(user_id, bool) and user_id in legacy:
        granted |= LEGACY_OPERATOR_PERMISSIONS
    return granted


def _normalize_email(email):
    if not isinstance(email, str):
        raise PlatformError("invalid_email", 422)
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise PlatformError("invalid_email", 422)
    return email


def _check_can_manage(actor_permissions, role_key):
    if role_key == "platform_owner":
        raise PlatformError("owner_requires_transfer", 409)
    if role_key in RESERVED_ROLES:
        raise PlatformError("role_not_enabled", 422)
    needed = _MANAGE_PERMISSION.get(role_key)
    if needed is None:
        raise PlatformError("invalid_role", 422)
    if needed not in actor_permissions:
        raise PlatformError("forbidden", 403)


def assignment_dict(row, emails=None):
    emails = emails or {}
    return {
        "id": row.id, "user_id": row.user_id, "email": emails.get(row.user_id),
        "role": row.role_key, "role_label": ROLE_LABELS.get(row.role_key, row.role_key),
        "scope_type": row.scope_type, "status": row.status,
        "granted_by": row.granted_by, "granted_by_email": emails.get(row.granted_by),
        "granted_at": row.granted_at.isoformat() if row.granted_at else None,
    }


def list_assignments():
    rows = db.session.scalars(select(PlatformRoleAssignment).where(
        PlatformRoleAssignment.status == "active").order_by(PlatformRoleAssignment.id)).all()
    emails = _emails({r.user_id for r in rows} | {r.granted_by for r in rows if r.granted_by})
    return [assignment_dict(r, emails) for r in rows]


def _grant(user_id, role_key, actor_id):
    existing = db.session.scalar(select(PlatformRoleAssignment).where(
        PlatformRoleAssignment.user_id == user_id, PlatformRoleAssignment.role_key == role_key,
        PlatformRoleAssignment.status == "active"))
    if existing is not None:
        raise PlatformError("role_already_assigned", 409)
    row = PlatformRoleAssignment(user_id=user_id, role_key=role_key, scope_type="platform",
                                 status="active", active_flag=1, granted_by=actor_id, granted_at=now())
    db.session.add(row)
    db.session.flush()
    record_audit(actor_id, "platform_role.grant", target_type="user", target_id=user_id,
                 details={"role": role_key, "assignment_id": row.id})
    return row


def grant_role(actor_id, actor_permissions, email, role_key):
    """Asigna un rol a una cuenta existente; si no existe, crea una invitación."""
    _check_can_manage(actor_permissions, role_key)
    email = _normalize_email(email)
    user = db.session.scalar(select(User).where(User.email == email))
    if user is None:
        return None, create_platform_invitation(actor_id, email, role_key)
    try:
        row = _grant(user.id, role_key, actor_id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise PlatformError("role_already_assigned", 409)
    return row, None


def revoke_role(actor_id, actor_permissions, assignment_id):
    row = db.session.scalar(select(PlatformRoleAssignment).where(
        PlatformRoleAssignment.id == assignment_id).with_for_update())
    if row is None or row.status != "active":
        raise PlatformError("assignment_not_found", 404)
    if row.role_key == "platform_owner":
        raise PlatformError("owner_requires_transfer", 409)
    _check_can_manage(actor_permissions, row.role_key)
    row.status, row.active_flag, row.revoked_by, row.revoked_at = "revoked", None, actor_id, now()
    record_audit(actor_id, "platform_role.revoke", target_type="user", target_id=row.user_id,
                 details={"role": row.role_key, "assignment_id": row.id})
    db.session.commit()
    return row


def _active_owner_rows(lock=False):
    query = select(PlatformRoleAssignment).where(
        PlatformRoleAssignment.role_key == "platform_owner", PlatformRoleAssignment.status == "active")
    if lock:
        query = query.with_for_update()
    return db.session.scalars(query).all()


def transfer_ownership(actor_id, email, *, keep_admin=True):
    """Transfiere el rol de dueño a otra cuenta. Primero se otorga y después se
    revoca al actual, en la misma transacción: nunca hay cero dueños."""
    email = _normalize_email(email)
    owners = _active_owner_rows(lock=True)
    mine = next((o for o in owners if o.user_id == actor_id), None)
    if mine is None:
        raise PlatformError("forbidden", 403)
    target = db.session.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if target is None:
        raise PlatformError("user_not_found", 404)
    if target.id == actor_id:
        raise PlatformError("cannot_transfer_to_self", 409)
    if any(o.user_id == target.id for o in owners):
        raise PlatformError("role_already_assigned", 409)
    try:
        _grant(target.id, "platform_owner", actor_id)
        mine.status, mine.active_flag, mine.revoked_by, mine.revoked_at = "revoked", None, actor_id, now()
        db.session.flush()
        if keep_admin and "platform_admin" not in active_roles(actor_id):
            _grant(actor_id, "platform_admin", actor_id)
        if not _active_owner_rows():
            raise PlatformError("platform_requires_owner", 409)
        record_audit(actor_id, "platform_owner.transfer", target_type="user", target_id=target.id,
                     details={"from_user_id": actor_id, "to_user_id": target.id, "keep_admin": keep_admin})
        db.session.commit()
    except (PlatformError, IntegrityError):
        db.session.rollback()
        raise
    return target


def bootstrap_owner(email):
    """Primer dueño (script de instalación). Falla si ya existe uno."""
    email = _normalize_email(email)
    if _active_owner_rows(lock=True):
        raise PlatformError("owner_already_exists", 409)
    user = db.session.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if user is None:
        raise PlatformError("user_not_found", 404)
    row = _grant(user.id, "platform_owner", None)
    db.session.commit()
    return row


# ----------------------------------------------------------------------------
# Invitaciones de plataforma (personas sin cuenta)
# ----------------------------------------------------------------------------

def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_platform_invitation(actor_id, email, role_key):
    pending = db.session.scalar(select(PlatformInvitation).where(
        PlatformInvitation.email == email, PlatformInvitation.role_key == role_key,
        PlatformInvitation.status == "pending").with_for_update())
    if pending is not None:
        if pending.expires_at > now():
            raise PlatformError("invitation_already_pending", 409)
        pending.status = "revoked"
    token = secrets.token_urlsafe(32)
    days = int(current_app.config.get("INVITATION_TTL_DAYS", 7))
    inv = PlatformInvitation(email=email, role_key=role_key, token_hash=_token_hash(token),
                             status="pending", invited_by=actor_id, created_at=now(),
                             expires_at=now() + timedelta(days=days))
    db.session.add(inv)
    db.session.flush()
    record_audit(actor_id, "platform_role.invite", target_type="platform_invitation", target_id=inv.id,
                 details={"role": role_key, "email": email})
    db.session.commit()
    return inv, token


def _pending_invitation(token, lock=False):
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        raise PlatformError("invalid_invitation", 404)
    query = select(PlatformInvitation).where(PlatformInvitation.token_hash == _token_hash(token))
    if lock:
        query = query.with_for_update()
    inv = db.session.scalar(query)
    if inv is None or inv.status != "pending" or inv.expires_at <= now():
        raise PlatformError("invalid_invitation", 404)
    return inv


def lookup_platform_invitation(token):
    inv = _pending_invitation(token)
    exists = db.session.scalar(select(User.id).where(User.email == inv.email)) is not None
    return {"email": inv.email, "role": inv.role_key, "role_label": ROLE_LABELS.get(inv.role_key),
            "user_exists": exists, "expires_at": inv.expires_at.isoformat()}


def accept_platform_invitation(token, password):
    if not isinstance(password, str):
        raise PlatformError("invalid_password", 422)
    try:
        inv = _pending_invitation(token, lock=True)
        user = db.session.scalar(select(User).where(User.email == inv.email))
        if user is None:
            if not 12 <= len(password) <= 256:
                raise PlatformError("invalid_password", 422)
            user = User(email=inv.email, password_hash=generate_password_hash(password), is_active=True)
            db.session.add(user)
            db.session.flush()
        elif not user.is_active or not check_password_hash(user.password_hash, password):
            raise PlatformError("invalid_credentials", 401)
        _grant(user.id, inv.role_key, inv.invited_by)
        inv.status, inv.accepted_at, inv.accepted_user_id = "accepted", now(), user.id
        db.session.commit()
        return {"accepted": True, "email": user.email, "role": inv.role_key}
    except PlatformError:
        db.session.rollback()
        raise
    except IntegrityError:
        db.session.rollback()
        raise PlatformError("invitation_conflict", 409)


def list_platform_invitations():
    rows = db.session.scalars(select(PlatformInvitation).where(
        PlatformInvitation.status == "pending", PlatformInvitation.expires_at > now())
        .order_by(PlatformInvitation.id.desc())).all()
    return [{"id": r.id, "email": r.email, "role": r.role_key, "role_label": ROLE_LABELS.get(r.role_key),
             "expires_at": r.expires_at.isoformat()} for r in rows]


def revoke_platform_invitation(actor_id, actor_permissions, invitation_id):
    inv = db.session.scalar(select(PlatformInvitation).where(
        PlatformInvitation.id == invitation_id).with_for_update())
    if inv is None or inv.status != "pending":
        raise PlatformError("invitation_not_found", 404)
    _check_can_manage(actor_permissions, inv.role_key)
    inv.status = "revoked"
    record_audit(actor_id, "platform_role.invite_revoke", target_type="platform_invitation",
                 target_id=inv.id, details={"role": inv.role_key, "email": inv.email})
    db.session.commit()


# ----------------------------------------------------------------------------
# Organizaciones (sin contenido privado)
# ----------------------------------------------------------------------------

def organization_dict(tenant, *, members=0, subscription=None, referral=None):
    return {
        "id": tenant.id, "name": tenant.name, "slug": tenant.slug, "status": tenant.status,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "members": members, "subscription_status": subscription, "referred": referral is not None,
    }


def _subscription_status(tenant_ids):
    if not tenant_ids:
        return {}
    from app.models.billing import TenantSubscription
    rows = db.session.execute(select(TenantSubscription.tenant_id, TenantSubscription.status).where(
        TenantSubscription.tenant_id.in_(tenant_ids)).order_by(TenantSubscription.id)).all()
    return {tenant_id: status for tenant_id, status in rows}


def list_organizations(*, search=None, status=None, page=1, per_page=20):
    query = select(Tenant).order_by(Tenant.id.desc())
    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(Tenant.name.like(like), Tenant.slug.like(like)))
    if status in ("active", "suspended"):
        query = query.where(Tenant.status == status)
    result = db.paginate(query, page=page, per_page=per_page, error_out=False)
    ids = [t.id for t in result.items]
    counts = dict(db.session.execute(select(Membership.tenant_id, func.count(Membership.id)).where(
        Membership.tenant_id.in_(ids), Membership.status == "active").group_by(Membership.tenant_id)).all()) if ids else {}
    subs = _subscription_status(ids)
    referred = set(db.session.scalars(select(TenantReferral.tenant_id).where(
        TenantReferral.tenant_id.in_(ids))).all()) if ids else set()
    items = [organization_dict(t, members=counts.get(t.id, 0), subscription=subs.get(t.id),
                               referral=True if t.id in referred else None) for t in result.items]
    return result, items


def create_organization(actor_id, name, slug, owner_email):
    """Alta de organización por la plataforma: crea la empresa y envía la
    invitación al dueño (rol owner de la organización)."""
    if not isinstance(name, str) or not 3 <= len(name.strip()) <= 180:
        raise PlatformError("invalid_name", 422)
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug.strip().lower()):
        raise PlatformError("invalid_slug", 422)
    email = _normalize_email(owner_email)
    slug = slug.strip().lower()
    if db.session.scalar(select(Tenant.id).where(Tenant.slug == slug)) is not None:
        raise PlatformError("slug_taken", 409)
    tenant = Tenant(name=name.strip(), slug=slug, status="active")
    db.session.add(tenant)
    db.session.flush()
    from app.services.members_service import ensure_owner_role
    ensure_owner_role(tenant.id)
    token = secrets.token_urlsafe(32)
    days = int(current_app.config.get("INVITATION_TTL_DAYS", 7))
    from app.services.members_service import _token_hash as member_token_hash
    inv = TenantInvitation(tenant_id=tenant.id, email=email, role_key="owner",
                           token_hash=member_token_hash(token), status="pending", invited_by=actor_id,
                           created_at=now(), expires_at=now() + timedelta(days=days))
    db.session.add(inv)
    record_audit(actor_id, "organization.create", tenant_id=tenant.id, target_type="tenant",
                 target_id=tenant.id, details={"name": tenant.name, "slug": slug, "owner_email": email})
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise PlatformError("slug_taken", 409)
    return tenant, inv, token


def set_organization_status(actor_id, tenant_id, status, reason):
    if status not in ("active", "suspended"):
        raise PlatformError("invalid_status", 422)
    if reason is not None and (not isinstance(reason, str) or len(reason) > 500):
        raise PlatformError("invalid_reason", 422)
    tenant = db.session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise PlatformError("organization_not_found", 404)
    if tenant.status == status:
        raise PlatformError("status_unchanged", 409)
    previous, tenant.status = tenant.status, status
    record_audit(actor_id, "organization.suspend" if status == "suspended" else "organization.activate",
                 tenant_id=tenant.id, target_type="tenant", target_id=tenant.id,
                 details={"previous": previous, "status": status, "reason": (reason or "").strip() or None})
    db.session.commit()
    return tenant


# ----------------------------------------------------------------------------
# Accesos delegados (solo lectura, con vencimiento y revocación)
# ----------------------------------------------------------------------------

MAX_GRANT_DAYS = 30


def active_grant(tenant_id, user_id):
    return db.session.scalar(select(TenantAccessGrant).where(
        TenantAccessGrant.tenant_id == tenant_id, TenantAccessGrant.grantee_user_id == user_id,
        TenantAccessGrant.revoked_at.is_(None), TenantAccessGrant.expires_at > now())
        .order_by(TenantAccessGrant.expires_at.desc()))


def grant_dict(grant, emails=None):
    emails = emails or {}
    state = "revoked" if grant.revoked_at else ("expired" if grant.expires_at <= now() else "active")
    return {
        "id": grant.id, "tenant_id": grant.tenant_id, "grantee_user_id": grant.grantee_user_id,
        "grantee_email": emails.get(grant.grantee_user_id), "purpose": grant.purpose,
        "access_level": grant.access_level, "reason": grant.reason, "state": state,
        "granted_by_email": emails.get(grant.granted_by),
        "granted_at": grant.granted_at.isoformat() if grant.granted_at else None,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
    }


def list_grants(tenant_id):
    rows = db.session.scalars(select(TenantAccessGrant).where(
        TenantAccessGrant.tenant_id == tenant_id).order_by(TenantAccessGrant.id.desc()).limit(100)).all()
    emails = _emails({r.grantee_user_id for r in rows} | {r.granted_by for r in rows})
    return [grant_dict(r, emails) for r in rows]


def create_grant(tenant_id, actor_id, email, purpose, days, reason):
    if purpose not in ("support", "training"):
        raise PlatformError("invalid_purpose", 422)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_GRANT_DAYS:
        raise PlatformError("invalid_days", 422, max_days=MAX_GRANT_DAYS)
    if reason is not None and (not isinstance(reason, str) or len(reason) > 500):
        raise PlatformError("invalid_reason", 422)
    email = _normalize_email(email)
    user = db.session.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if user is None:
        raise PlatformError("user_not_found", 404)
    if user.id == actor_id:
        raise PlatformError("cannot_grant_self", 409)
    if db.session.scalar(select(Membership.id).where(
            Membership.tenant_id == tenant_id, Membership.user_id == user.id)) is not None:
        raise PlatformError("already_member", 409)
    roles = active_roles(user.id)
    # Soporte: solo personal de plataforma. Capacitación: solo el promotor que refirió a la organización.
    if purpose == "support" and not roles & {"platform_owner", "platform_admin"}:
        raise PlatformError("grantee_not_platform_staff", 422)
    if purpose == "training":
        referral = db.session.scalar(select(TenantReferral).where(TenantReferral.tenant_id == tenant_id))
        if "promoter" not in roles or referral is None or referral.promoter_user_id != user.id:
            raise PlatformError("grantee_not_referring_promoter", 422)
    if active_grant(tenant_id, user.id) is not None:
        raise PlatformError("grant_already_active", 409)
    grant = TenantAccessGrant(tenant_id=tenant_id, grantee_user_id=user.id, purpose=purpose,
                              access_level="read_only", reason=(reason or "").strip() or None,
                              granted_by=actor_id, granted_at=now(), expires_at=now() + timedelta(days=days))
    db.session.add(grant)
    db.session.flush()
    record_audit(actor_id, "access_grant.create", tenant_id=tenant_id, target_type="access_grant",
                 target_id=grant.id, details={"grantee_user_id": user.id, "purpose": purpose, "days": days})
    db.session.commit()
    return grant


def revoke_grant(tenant_id, actor_id, grant_id):
    grant = db.session.scalar(select(TenantAccessGrant).where(
        TenantAccessGrant.id == grant_id, TenantAccessGrant.tenant_id == tenant_id).with_for_update())
    if grant is None:
        raise PlatformError("grant_not_found", 404)
    if grant.revoked_at is not None:
        raise PlatformError("grant_already_revoked", 409)
    grant.revoked_at, grant.revoked_by = now(), actor_id
    record_audit(actor_id, "access_grant.revoke", tenant_id=tenant_id, target_type="access_grant",
                 target_id=grant.id, details={"grantee_user_id": grant.grantee_user_id})
    db.session.commit()
    return grant


def delegated_tenants(user_id):
    rows = db.session.execute(select(TenantAccessGrant, Tenant).join(
        Tenant, Tenant.id == TenantAccessGrant.tenant_id).where(
        TenantAccessGrant.grantee_user_id == user_id, TenantAccessGrant.revoked_at.is_(None),
        TenantAccessGrant.expires_at > now())).all()
    return [{"id": t.id, "name": t.name, "slug": t.slug, "role": "delegated", "status": t.status,
             "purpose": g.purpose, "expires_at": g.expires_at.isoformat()} for g, t in rows]


# ----------------------------------------------------------------------------
# Promotores
# ----------------------------------------------------------------------------

def referral_code(user_id):
    row = db.session.scalar(select(PromoterReferralCode).where(PromoterReferralCode.promoter_user_id == user_id))
    if row is None:
        for _ in range(5):
            code = secrets.token_hex(5).upper()
            if db.session.scalar(select(PromoterReferralCode.id).where(PromoterReferralCode.code == code)) is None:
                break
        row = PromoterReferralCode(promoter_user_id=user_id, code=code, created_at=now())
        db.session.add(row)
        db.session.commit()
    return row.code


def referral_link(code):
    base = current_app.config.get("FRONTEND_PUBLIC_URL", "").rstrip("/")
    return f"{base}/register?ref={code}"


def prospect_dict(p):
    return {
        "id": p.id, "company_name": p.company_name, "contact_name": p.contact_name,
        "contact_email": p.contact_email, "phone": p.phone, "notes": p.notes, "status": p.status,
        "tenant_id": p.tenant_id,
        "invited_at": p.invited_at.isoformat() if p.invited_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


_PROSPECT_FIELDS = {"company_name": 180, "contact_name": 180, "contact_email": 254, "phone": 40, "notes": 1000}


def _clean_prospect(body, *, partial):
    if not isinstance(body, dict):
        raise PlatformError("invalid_json", 400)
    unknown = set(body) - set(_PROSPECT_FIELDS) - {"status"}
    if unknown:
        raise PlatformError("invalid_fields", 422, fields=sorted(unknown))
    cleaned = {}
    for field, limit in _PROSPECT_FIELDS.items():
        if field not in body:
            continue
        value = body[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            cleaned[field] = None
            continue
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise PlatformError(f"invalid_{field}", 422)
        cleaned[field] = value.strip()
    if cleaned.get("contact_email"):
        cleaned["contact_email"] = _normalize_email(cleaned["contact_email"])
    if not partial and not cleaned.get("company_name"):
        raise PlatformError("invalid_company_name", 422)
    if partial and "company_name" in cleaned and not cleaned["company_name"]:
        raise PlatformError("invalid_company_name", 422)
    if "status" in body:
        # El promotor solo puede descartar o reactivar; el alta la registra el sistema.
        if body["status"] not in ("prospect", "discarded"):
            raise PlatformError("invalid_status", 422)
        cleaned["status"] = body["status"]
    return cleaned


def list_prospects(user_id):
    rows = db.session.scalars(select(PromoterProspect).where(
        PromoterProspect.promoter_user_id == user_id).order_by(PromoterProspect.id.desc())).all()
    return [prospect_dict(p) for p in rows]


def create_prospect(user_id, body):
    data = _clean_prospect(body, partial=False)
    data.pop("status", None)
    prospect = PromoterProspect(promoter_user_id=user_id, status="prospect", **data)
    db.session.add(prospect)
    db.session.commit()
    return prospect


def _own_prospect(user_id, prospect_id, lock=False):
    query = select(PromoterProspect).where(PromoterProspect.id == prospect_id,
                                           PromoterProspect.promoter_user_id == user_id)
    if lock:
        query = query.with_for_update()
    prospect = db.session.scalar(query)
    if prospect is None:
        raise PlatformError("prospect_not_found", 404)
    return prospect


def update_prospect(user_id, prospect_id, body):
    prospect = _own_prospect(user_id, prospect_id, lock=True)
    data = _clean_prospect(body, partial=True)
    if prospect.status == "registered" and "status" in data:
        raise PlatformError("prospect_already_registered", 409)
    for key, value in data.items():
        setattr(prospect, key, value)
    db.session.commit()
    return prospect


def mark_prospect_invited(user_id, prospect_id):
    prospect = _own_prospect(user_id, prospect_id, lock=True)
    if not prospect.contact_email:
        raise PlatformError("prospect_without_email", 422)
    if prospect.status in ("registered", "discarded"):
        raise PlatformError("prospect_not_invitable", 409)
    prospect.status, prospect.invited_at = "invited", now()
    db.session.commit()
    return prospect


def list_referrals(user_id):
    """Avance de las altas del promotor: nombre, fecha y estado, sin datos internos."""
    rows = db.session.execute(select(TenantReferral, Tenant).join(Tenant, Tenant.id == TenantReferral.tenant_id)
                              .where(TenantReferral.promoter_user_id == user_id)
                              .order_by(TenantReferral.id.desc())).all()
    subs = _subscription_status([t.id for _, t in rows])
    return [{"tenant_id": t.id, "organization": t.name, "status": t.status,
             "registered_at": r.created_at.isoformat() if r.created_at else None,
             "subscription_status": subs.get(t.id) or "free", "prospect_id": r.prospect_id}
            for r, t in rows]


def record_referral(tenant_id, owner_email, code):
    """Se llama al registrar una empresa con ``?ref=``. Un código inválido no impide el alta."""
    if not isinstance(code, str) or not 4 <= len(code.strip()) <= 16:
        return None
    row = db.session.scalar(select(PromoterReferralCode).where(PromoterReferralCode.code == code.strip().upper()))
    if row is None or "promoter" not in active_roles(row.promoter_user_id):
        return None
    prospect = db.session.scalar(select(PromoterProspect).where(
        PromoterProspect.promoter_user_id == row.promoter_user_id,
        PromoterProspect.contact_email == owner_email,
        PromoterProspect.status.in_(("prospect", "invited"))).order_by(PromoterProspect.id.desc()))
    if prospect is not None:
        prospect.status, prospect.tenant_id = "registered", tenant_id
    referral = TenantReferral(tenant_id=tenant_id, promoter_user_id=row.promoter_user_id,
                              prospect_id=prospect.id if prospect else None, code=row.code, created_at=now())
    db.session.add(referral)
    record_audit(None, "organization.referred", tenant_id=tenant_id, target_type="tenant",
                 target_id=tenant_id, details={"promoter_user_id": row.promoter_user_id})
    return referral
