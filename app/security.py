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

def tenant_permission(permission):
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
            if not membership:
                return jsonify(error='forbidden'), 403
            allowed = db.session.scalar(select(Permission.id).join(RolePermission, RolePermission.permission_id == Permission.id).where(
                RolePermission.role_id == membership.role_id, Permission.code == permission))
            if allowed is None:
                return jsonify(error='forbidden'), 403
            g.tenant_id = tenant_id
            g.membership = membership
            return fn(*args, **kwargs)
        return inner
    return outer
