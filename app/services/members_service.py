"""AUTH-02: miembros de una empresa, roles predefinidos e invitaciones.

Reglas:
- Los roles son plantillas fijas por empresa (se crean bajo demanda); el rol
  ``owner`` no se asigna ni se modifica desde aquí.
- Nadie puede cambiar su propio rol ni desactivarse a sí mismo.
- Las invitaciones son de un solo uso, caducan y se guardan solo como hash.
- El límite de usuarios del plan se valida al invitar y otra vez al aceptar.
"""
import hashlib
import re
import secrets
from datetime import timedelta

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import Tenant
from app.models.identity import (
    Membership, Permission, Role, RolePermission, TenantInvitation, User, now,
)

OWNER_PERMISSIONS = (
    "tenant.read",
    "members.read", "members.manage",
    "billing.manage",
    "clients.read", "clients.create", "clients.update",
    "events.read", "events.create", "events.update",
    "inventory.read", "inventory.create", "inventory.update", "inventory.adjust",
    "inventory.charges.approve", "inventory.charges.pay",
    "quotes.create", "quotes.read",
    "contracts.create", "contracts.read", "contracts.update",
    "catalog.read", "catalog.manage",
)

ROLE_TEMPLATES = {
    # Todo excepto contratar o cancelar la suscripción.
    "admin": tuple(code for code in OWNER_PERMISSIONS if code != "billing.manage"),
    # Operación diaria, sin aprobar cobros por daños, sin miembros ni facturación.
    "staff": (
        "tenant.read",
        "clients.read", "clients.create", "clients.update",
        "events.read", "events.create", "events.update",
        "inventory.read", "inventory.create", "inventory.update", "inventory.adjust",
        "quotes.create", "quotes.read",
        "contracts.create", "contracts.read", "contracts.update",
        "catalog.read", "catalog.manage",
    ),
    "viewer": (
        "tenant.read", "clients.read", "events.read", "inventory.read", "quotes.read", "contracts.read",
        "catalog.read",
    ),
    # CAT-01: proveedor externo; solo ve y confirma sus propias partidas.
    "provider": ("tenant.read", "provider.items"),
}
ASSIGNABLE_ROLES = frozenset(ROLE_TEMPLATES)
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class MembersError(Exception):
    def __init__(self, code, status=400, **extra):
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _permission(code):
    permission = db.session.scalar(select(Permission).where(Permission.code == code))
    if permission is None:
        permission = Permission(code=code)
        db.session.add(permission)
        db.session.flush()
    return permission


def _sync_role(tenant_id, role_name, codes):
    """Crea el rol si falta y agrega los permisos de la plantilla que le falten
    (solo agrega: nunca retira permisos de un rol existente)."""
    role = db.session.scalar(select(Role).where(Role.tenant_id == tenant_id, Role.name == role_name))
    if role is None:
        role = Role(tenant_id=tenant_id, name=role_name)
        db.session.add(role)
        db.session.flush()
    current = set(db.session.scalars(select(Permission.code).join(
        RolePermission, RolePermission.permission_id == Permission.id).where(
        RolePermission.role_id == role.id)).all())
    for code in codes:
        if code not in current:
            db.session.add(RolePermission(role_id=role.id, permission_id=_permission(code).id))
    db.session.flush()
    return role


def ensure_role(tenant_id, role_key):
    """Devuelve el rol plantilla de la empresa, creándolo con sus permisos si falta."""
    if role_key not in ASSIGNABLE_ROLES:
        raise MembersError("invalid_role", 422)
    return _sync_role(tenant_id, role_key, ROLE_TEMPLATES[role_key])


def ensure_owner_role(tenant_id):
    """Rol propietario (no asignable desde la gestión de miembros)."""
    return _sync_role(tenant_id, "owner", OWNER_PERMISSIONS)


def _normalize_email(email):
    if not isinstance(email, str):
        raise MembersError("invalid_email", 422)
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise MembersError("invalid_email", 422)
    return email


def _check_member_limit(tenant_id, *, extra_pending=True):
    """Aplica el límite 'members' del plan si la facturación está activada."""
    if not current_app.config.get("BILLING_ENFORCE_ENTITLEMENTS", False):
        return
    from app.services.billing.entitlements_service import entitlement
    result = entitlement(tenant_id, "members")
    if not result["allowed"]:
        raise MembersError("billing_entitlement_denied", 403, feature_code="members",
                           reason=result["reason"], limit=result["limit"], used=result["used"],
                           tier=result.get("tier"))
    limit = result.get("limit")
    if extra_pending and limit is not None:
        pending = db.session.scalar(select(func.count(TenantInvitation.id)).where(
            TenantInvitation.tenant_id == tenant_id, TenantInvitation.status == "pending",
            TenantInvitation.expires_at > now())) or 0
        used = result.get("used") or 0
        if used + pending >= limit:
            raise MembersError("billing_entitlement_denied", 403, feature_code="members",
                               reason="limit_reached", limit=limit, used=used + pending,
                               tier=result.get("tier"))


def invitation_dict(inv):
    return {
        "id": inv.id, "email": inv.email, "role": inv.role_key, "status": inv.status,
        "provider_id": inv.provider_id,
        "expired": inv.status == "pending" and inv.expires_at <= now(),
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
    }


def _provider_for_role(tenant_id, role_key, provider_id):
    if role_key != "provider":
        if provider_id is not None:
            raise MembersError("provider_only_for_provider_role", 422)
        return None
    from app.models.catalog import Provider
    if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0:
        raise MembersError("provider_required", 422)
    provider = db.session.scalar(select(Provider).where(
        Provider.id == provider_id, Provider.tenant_id == tenant_id, Provider.status == "active"))
    if provider is None:
        raise MembersError("provider_not_found", 404)
    return provider.id


def create_invitation(tenant_id, actor_id, email, role_key, provider_id=None):
    email = _normalize_email(email)
    if role_key not in ASSIGNABLE_ROLES:
        raise MembersError("invalid_role", 422)
    provider_id = _provider_for_role(tenant_id, role_key, provider_id)
    # Serializa invitaciones concurrentes de la misma empresa (límite del plan).
    db.session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    existing_user = db.session.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        member = db.session.scalar(select(Membership).where(
            Membership.tenant_id == tenant_id, Membership.user_id == existing_user.id))
        if member is not None:
            raise MembersError("already_member", 409)
    pending = db.session.scalar(select(TenantInvitation).where(
        TenantInvitation.tenant_id == tenant_id, TenantInvitation.email == email,
        TenantInvitation.status == "pending").with_for_update())
    if pending is not None:
        if pending.expires_at > now():
            raise MembersError("invitation_already_pending", 409)
        pending.status = "revoked"  # caducada: se reemplaza por una nueva
    _check_member_limit(tenant_id)
    token = secrets.token_urlsafe(32)
    days = int(current_app.config.get("INVITATION_TTL_DAYS", 7))
    inv = TenantInvitation(tenant_id=tenant_id, email=email, role_key=role_key, provider_id=provider_id,
                           token_hash=_token_hash(token),
                           status="pending", invited_by=actor_id, created_at=now(),
                           expires_at=now() + timedelta(days=days))
    db.session.add(inv)
    db.session.flush()
    _audit(actor_id, "member.invite", tenant_id, "invitation", inv.id,
           {"email": email, "role": role_key, "provider_id": provider_id})
    db.session.commit()
    return inv, token


def revoke_invitation(tenant_id, invitation_id):
    inv = db.session.scalar(select(TenantInvitation).where(
        TenantInvitation.id == invitation_id, TenantInvitation.tenant_id == tenant_id).with_for_update())
    if inv is None:
        raise MembersError("invitation_not_found", 404)
    if inv.status != "pending":
        raise MembersError("invitation_not_pending", 409)
    inv.status = "revoked"
    db.session.commit()
    return inv


def _pending_by_token(token, *, lock=False):
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        raise MembersError("invalid_invitation", 404)
    query = select(TenantInvitation).where(TenantInvitation.token_hash == _token_hash(token))
    if lock:
        query = query.with_for_update()
    inv = db.session.scalar(query)
    if inv is None or inv.status != "pending" or inv.expires_at <= now():
        raise MembersError("invalid_invitation", 404)
    return inv


def lookup_invitation(token):
    inv = _pending_by_token(token)
    tenant = db.session.get(Tenant, inv.tenant_id)
    user_exists = db.session.scalar(select(User.id).where(User.email == inv.email)) is not None
    return {"tenant_name": tenant.name if tenant else None, "email": inv.email,
            "role": inv.role_key, "user_exists": user_exists,
            "expires_at": inv.expires_at.isoformat()}


def accept_invitation(token, password):
    """Acepta la invitación. Cuenta nueva: crea el usuario con ``password``.
    Cuenta existente: ``password`` debe ser la contraseña actual de esa cuenta."""
    if not isinstance(password, str):
        raise MembersError("invalid_password", 422)
    try:
        inv = _pending_by_token(token, lock=True)
        db.session.scalar(select(Tenant).where(Tenant.id == inv.tenant_id).with_for_update())
        user = db.session.scalar(select(User).where(User.email == inv.email))
        if user is None:
            if not 12 <= len(password) <= 256:
                raise MembersError("invalid_password", 422)
            user = User(email=inv.email, password_hash=generate_password_hash(password), is_active=True)
            db.session.add(user)
            db.session.flush()
        else:
            if not user.is_active or not check_password_hash(user.password_hash, password):
                raise MembersError("invalid_credentials", 401)
            if db.session.scalar(select(Membership.id).where(
                    Membership.tenant_id == inv.tenant_id, Membership.user_id == user.id)):
                raise MembersError("already_member", 409)
        _check_member_limit(inv.tenant_id, extra_pending=False)
        # «owner» solo llega aquí desde el alta de organización hecha por la plataforma.
        role = (ensure_owner_role(inv.tenant_id) if inv.role_key == "owner"
                else ensure_role(inv.tenant_id, inv.role_key))
        db.session.add(Membership(tenant_id=inv.tenant_id, user_id=user.id, role_id=role.id, status="active",
                                  provider_id=inv.provider_id if inv.role_key == "provider" else None))
        _audit(user.id, "member.join", inv.tenant_id, "invitation", inv.id, {"role": inv.role_key})
        inv.status, inv.accepted_at, inv.accepted_user_id = "accepted", now(), user.id
        db.session.commit()
        return {"accepted": True, "tenant_id": inv.tenant_id, "email": user.email}
    except MembersError:
        db.session.rollback()
        raise
    except IntegrityError:
        db.session.rollback()
        raise MembersError("invitation_conflict", 409)


def _target_membership(tenant_id, membership_id, actor_id):
    member = db.session.scalar(select(Membership).where(
        Membership.id == membership_id, Membership.tenant_id == tenant_id).with_for_update())
    if member is None:
        raise MembersError("member_not_found", 404)
    if member.user_id == actor_id:
        raise MembersError("cannot_modify_self", 409)
    role = db.session.get(Role, member.role_id)
    if role is not None and role.name == "owner":
        raise MembersError("cannot_modify_owner", 409)
    return member


def _audit(actor_id, action, tenant_id, target_type, target_id, details):
    from app.services.platform_service import record_audit
    record_audit(actor_id, action, tenant_id=tenant_id, target_type=target_type,
                 target_id=target_id, details=details)


def change_role(tenant_id, membership_id, actor_id, role_key, provider_id=None):
    member = _target_membership(tenant_id, membership_id, actor_id)
    if role_key not in ASSIGNABLE_ROLES:
        raise MembersError("invalid_role", 422)
    provider_id = _provider_for_role(tenant_id, role_key, provider_id)
    previous = db.session.get(Role, member.role_id)
    member.role_id = ensure_role(tenant_id, role_key).id
    member.provider_id = provider_id
    _audit(actor_id, "member.role_change", tenant_id, "membership", member.id,
           {"user_id": member.user_id, "from": previous.name if previous else None, "to": role_key,
            "provider_id": provider_id})
    db.session.commit()
    return member


def set_member_status(tenant_id, membership_id, actor_id, active):
    member = _target_membership(tenant_id, membership_id, actor_id)
    desired = "active" if active else "inactive"
    if member.status == desired:
        raise MembersError("status_unchanged", 409)
    if active:
        _check_member_limit(tenant_id, extra_pending=False)
    member.status = desired
    _audit(actor_id, "member.activate" if active else "member.deactivate", tenant_id, "membership",
           member.id, {"user_id": member.user_id})
    db.session.commit()
    return member
