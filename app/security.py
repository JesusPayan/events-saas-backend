from functools import wraps
from flask import request, jsonify, g, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import select
from app.extensions import db

from app.models import Tenant
from app.models.identity import User, Role, Permission, RolePermission, Membership

import hashlib
import time


def serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='eventos-auth-v1')


def session_version(user):
    """Huella de la contraseña actual: cambiarla invalida todas las sesiones y enlaces."""
    password_hash = getattr(user, 'password_hash', None)
    if not isinstance(password_hash, str):
        return None
    return hashlib.sha256(password_hash.encode('utf-8')).hexdigest()[:16]


def issue_token(user_id, *, user=None, session_started=None):
    """Emite un token de acceso (vigencia TOKEN_MAX_AGE).

    ``sv`` liga el token a la contraseña vigente; ``iat0`` conserva el inicio de la
    sesión original para limitar su duración total (SESSION_MAX_AGE) aunque se renueve.
    """
    if user is None:
        try:
            user = db.session.get(User, user_id)
        except Exception:  # sin base de datos (pruebas unitarias con mocks)
            user = None
    return serializer().dumps({
        'uid': user_id,
        'sv': session_version(user),
        'iat0': int(session_started or time.time()),
    })

def authenticate(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        header = request.headers.get('Authorization','')
        if not header.startswith('Bearer '):
            return jsonify(error='authentication_required'), 401
        try:
            data = serializer().loads(header[7:], max_age=current_app.config.get('TOKEN_MAX_AGE',3600))
            user = db.session.get(User, data['uid'])
        except (BadSignature, SignatureExpired, KeyError, TypeError):
            return jsonify(error='invalid_token'), 401
        if user is None or not user.is_active:
            return jsonify(error='invalid_token'), 401
        # Contraseña cambiada desde que se emitió el token: sesión revocada.
        if data.get('sv') != session_version(user):
            return jsonify(error='invalid_token'), 401
        started = data.get('iat0')
        max_session = current_app.config.get('SESSION_MAX_AGE', 12 * 3600)
        if isinstance(started, int) and time.time() - started > max_session:
            return jsonify(error='session_expired'), 401
        g.user = user
        g.session_started = started if isinstance(started, int) else int(time.time())
        return fn(*args, **kwargs)
    return inner

# Permisos que concede un acceso delegado (solo lectura). Lista cerrada: aunque se
# agreguen permisos nuevos al sistema, el acceso delegado no los hereda.
DELEGATED_READ_PERMISSIONS = frozenset({
    "tenant.read", "clients.read", "events.read", "inventory.read",
    "quotes.read", "contracts.read", "catalog.read",
})


def _role_allows(role_id, permission):
    return db.session.scalar(select(Permission.id).join(
        RolePermission, RolePermission.permission_id == Permission.id).where(
        RolePermission.role_id == role_id, Permission.code == permission)) is not None


def tenant_permission(permission):
    """Valida usuario, organización (X-Tenant-ID) y permiso en cada operación.

    - La organización debe estar activa (las suspendidas responden 403).
    - Sin membresía, se acepta un acceso delegado vigente solo para permisos de
      lectura; cada uso queda en la bitácora de auditoría.
    """
    def outer(fn):
        @wraps(fn)
        @authenticate
        def inner(*args, **kwargs):
            try:
                tenant_id = int(request.headers.get('X-Tenant-ID',''))
            except ValueError:
                return jsonify(error='tenant_required'), 400
            membership = db.session.scalar(select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == g.user.id,
                Membership.status == 'active'))
            grant = None
            if membership is not None:
                if not _role_allows(membership.role_id, permission):
                    return jsonify(error='forbidden'), 403
            else:
                from app.services.platform_service import active_grant, record_audit
                grant = active_grant(tenant_id, g.user.id)
                if grant is None or permission not in DELEGATED_READ_PERMISSIONS:
                    return jsonify(error='forbidden'), 403
            tenant_status = db.session.scalar(select(Tenant.status).where(Tenant.id == tenant_id))
            if tenant_status != 'active':
                return jsonify(error='tenant_suspended'), 403
            # MOD-01: módulo habilitado y dentro del plan (lecturas siempre permitidas
            # para conservar el acceso a datos históricos).
            from app.modules_registry import module_for_endpoint
            module_code = module_for_endpoint(request.endpoint)
            if module_code is not None:
                from app.services.capability_service import SAFE_METHODS, can_access_module
                denied = can_access_module(tenant_id, module_code,
                                           write=request.method not in SAFE_METHODS)
                if denied:
                    return jsonify(error=denied, module=module_code), 403
            g.tenant_id = tenant_id
            g.membership = membership
            g.access_grant = grant
            if grant is not None:
                record_audit(g.user.id, 'delegated_access.use', tenant_id=tenant_id,
                             target_type='access_grant', target_id=grant.id,
                             details={'method': request.method, 'path': request.path,
                                      'permission': permission}, commit=True)
            return fn(*args, **kwargs)
        return inner
    return outer


def platform_permission(*permissions):
    """Exige al menos uno de los permisos de plataforma indicados (alcance global)."""
    def outer(fn):
        @wraps(fn)
        @authenticate
        def inner(*args, **kwargs):
            from app.services.platform_service import platform_permissions
            granted = platform_permissions(g.user.id)
            if not granted.intersection(permissions):
                return jsonify(error='forbidden'), 403
            g.platform_permissions = granted
            return fn(*args, **kwargs)
        return inner
    return outer
