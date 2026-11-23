
import re
from datetime import datetime

from flask import Blueprint, request, jsonify, g, current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db, limiter
from app.models import Tenant
from app.models.identity import User, Role, Permission, RolePermission, Membership
from app.security import authenticate, tenant_permission, issue_token, session_version
from app.services.members_service import OWNER_PERMISSIONS
from app.services.email_service import EmailDeliveryError, send_email
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


bp = Blueprint("auth", __name__)

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,98}[a-z0-9])?")

# Permisos del rol propietario: fuente única en members_service.
OWNER_PERMISSION_CODES = OWNER_PERMISSIONS


@bp.post("/auth/register")
@limiter.limit(lambda: current_app.config.get("RATELIMIT_REGISTER", "10 per hour"))
def register():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400

    email = data.get("email", "")
    password = data.get("password", "")
    slug = data.get("slug", "")
    name = data.get("company_name", "")

    if not all(
        isinstance(value, str)
        for value in (email, password, slug, name)
    ):
        return jsonify(error="invalid_registration"), 400

    email = email.strip().lower()
    slug = slug.strip().lower()
    name = name.strip()

    if (
        not email
        or not slug
        or len(name) < 3
        or len(name) > 180
        or len(password) < 12
        or len(password) > 256
        or len(email) > 254
        or not _EMAIL_RE.fullmatch(email)
        or not _SLUG_RE.fullmatch(slug)
    ):
        return jsonify(error="invalid_registration"), 400

    try:
        # 1. Crear empresa
        tenant = Tenant(
            name=name,
            slug=slug,
            status="active"
        )
        db.session.add(tenant)
        db.session.flush()

        # 2. Crear usuario
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            is_active=True,
            created_at=datetime.now()
        )
        db.session.add(user)
        db.session.flush()

        # 3. Crear rol propietario
        role = Role(
            tenant_id=tenant.id,
            name="owner"
        )
        db.session.add(role)
        db.session.flush()

        # 4. Asignar permisos iniciales
        for code in OWNER_PERMISSION_CODES:
            permission = db.session.scalar(
                select(Permission).where(
                    Permission.code == code
                )
            )

            if permission is None:
                permission = Permission(code=code)
                db.session.add(permission)
                db.session.flush()

            db.session.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=permission.id
                )
            )

        # 5. Crear membresía
        membership = Membership(
            tenant_id=tenant.id,
            user_id=user.id,
            role_id=role.id
        )
        db.session.add(membership)

        # 6. Confirmar operación
        db.session.commit()

        return jsonify(
            user_id=user.id,
            tenant_id=tenant.id
        ), 201

    except IntegrityError:
        db.session.rollback()
        current_app.logger.exception(
            "Conflicto al registrar usuario y empresa"
        )
        return jsonify(error="registration_conflict"), 409

    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Error inesperado al registrar usuario y empresa"
        )
        return jsonify(error="internal_server_error"), 500


@bp.post("/auth/login")
@limiter.limit(lambda: current_app.config.get("RATELIMIT_LOGIN", "10 per minute"))
def login():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400

    email = str(data.get("email", "")).strip().lower()

    user = db.session.scalar(
        select(User).where(User.email == email)
    )

    if (
        user is None
        or not user.is_active
        or not check_password_hash(
            user.password_hash,
            str(data.get("password", ""))
        )
    ):
        return jsonify(error="invalid_credentials"), 401

    return jsonify(
        access_token=issue_token(user.id, user=user),
        token_type="Bearer",
        expires_in=current_app.config.get("TOKEN_MAX_AGE", 3600)
    ), 200


@bp.post("/auth/refresh")
@authenticate
def refresh():
    """Renueva el token sin extender la duración máxima de la sesión original."""
    return jsonify(
        access_token=issue_token(g.user.id, user=g.user, session_started=g.session_started),
        token_type="Bearer",
        expires_in=current_app.config.get("TOKEN_MAX_AGE", 3600)
    ), 200


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="eventos-password-reset-v1")


@bp.post("/auth/password/forgot")
@limiter.limit(lambda: current_app.config.get("RATELIMIT_PASSWORD_RESET", "5 per hour"))
def forgot_password():
    """Envía un enlace de restablecimiento. Responde igual exista o no el correo."""
    data = request.get_json(silent=True)
    email = str((data or {}).get("email", "")).strip().lower() if isinstance(data, dict) else ""
    user = db.session.scalar(select(User).where(User.email == email)) if email else None
    if user is not None and user.is_active:
        token = _reset_serializer().dumps({"uid": user.id, "sv": session_version(user)})
        base = current_app.config.get("FRONTEND_PUBLIC_URL", "").rstrip("/")
        try:
            send_email(
                to_email=user.email,
                subject="Restablece tu contraseña de Eventos SaaS",
                text_body=(
                    "Recibimos una solicitud para restablecer tu contraseña.\n\n"
                    f"Usa este enlace en la próxima hora:\n{base}/reset-password#token={token}\n\n"
                    "Si no lo solicitaste, ignora este correo: tu contraseña no cambiará."
                ),
            )
        except EmailDeliveryError:
            current_app.logger.warning("No se pudo enviar el correo de restablecimiento: user_id=%s", user.id)
    return jsonify(accepted=True), 202


@bp.post("/auth/password/reset")
@limiter.limit(lambda: current_app.config.get("RATELIMIT_PASSWORD_RESET", "10 per hour"))
def reset_password():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid_json"), 400
    token, password = data.get("token"), data.get("password")
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        return jsonify(error="invalid_password"), 422
    try:
        payload = _reset_serializer().loads(str(token or ""), max_age=current_app.config.get("PASSWORD_RESET_MAX_AGE", 3600))
    except (BadSignature, SignatureExpired):
        return jsonify(error="invalid_or_expired_token"), 400
    user = db.session.get(User, payload.get("uid")) if isinstance(payload, dict) else None
    # Un solo uso: tras cambiar la contraseña, 'sv' deja de coincidir.
    if user is None or not user.is_active or payload.get("sv") != session_version(user):
        return jsonify(error="invalid_or_expired_token"), 400
    user.password_hash = generate_password_hash(password)
    db.session.commit()  # invalida también todas las sesiones abiertas
    return jsonify(reset=True), 200


@bp.get("/auth/me")
@authenticate
def me():
    memberships = db.session.scalars(
        select(Membership).where(
            Membership.user_id == g.user.id,
            Membership.status == "active"
        )
    ).all()

    tenants_by_id = {
        t.id: t for t in db.session.scalars(
            select(Tenant).where(Tenant.id.in_([m.tenant_id for m in memberships]))
        ).all()
    } if memberships else {}
    roles_by_id = {
        r.id: r for r in db.session.scalars(
            select(Role).where(Role.id.in_([m.role_id for m in memberships]))
        ).all()
    } if memberships else {}

    return jsonify(
        id=g.user.id,
        email=g.user.email,
        tenants=[m.tenant_id for m in memberships],
        # Solo empresas de las que el usuario es miembro activo.
        tenant_details=[
            {
                "id": m.tenant_id,
                "name": tenants_by_id[m.tenant_id].name if m.tenant_id in tenants_by_id else None,
                "slug": tenants_by_id[m.tenant_id].slug if m.tenant_id in tenants_by_id else None,
                "role": roles_by_id[m.role_id].name if m.role_id in roles_by_id else None,
            }
            for m in memberships
        ],
    ), 200


@bp.get("/tenants/current")
@tenant_permission("tenant.read")
def current_tenant():
    tenant = db.session.get(Tenant, g.tenant_id)

    if tenant is None:
        return jsonify(error="tenant_not_found"), 404

    return jsonify(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug
    ), 200


@bp.get("/memberships")
@tenant_permission("members.read")
def members():
    memberships = db.session.scalars(
        select(Membership).where(
            Membership.tenant_id == g.tenant_id
        )
    ).all()

    users = {
        u.id: u for u in db.session.scalars(
            select(User).where(User.id.in_([m.user_id for m in memberships]))
        ).all()
    } if memberships else {}
    roles = {
        r.id: r for r in db.session.scalars(
            select(Role).where(Role.tenant_id == g.tenant_id)
        ).all()
    }

    return jsonify(
        items=[
            {
                "id": m.id,
                "user_id": m.user_id,
                "role_id": m.role_id,
                "status": m.status,
                "email": users[m.user_id].email if m.user_id in users else None,
                "role_name": roles[m.role_id].name if m.role_id in roles else None,
            }
            for m in memberships
        ]
    ), 200


@bp.get("/auth/permissions")
@tenant_permission("tenant.read")
def get_permissions():
    membership = db.session.scalar(
        select(Membership).where(
            Membership.user_id == g.user.id,
            Membership.tenant_id == g.tenant_id,
            Membership.status == "active"
        )
    )

    if membership is None:
        return jsonify(error="membership_not_found"), 403

    permissions = db.session.scalars(
        select(Permission.code)
        .join(
            RolePermission,
            RolePermission.permission_id == Permission.id
        )
        .where(
            RolePermission.role_id == membership.role_id
        )
        .distinct()
        .order_by(Permission.code)
    ).all()

    return jsonify(
        tenant_id=g.tenant_id,
        permissions=list(permissions)
    ), 200
