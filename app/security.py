from functools import wraps
from flask import request, jsonify, g, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import select
from app.extensions import db

from app.models import Tenant
from app.models.identity import User, Role, Permission, RolePermission, Membership

def serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='eventos-auth-v1')

def issue_token(user_id):
    return serializer().dumps({'uid': user_id})

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
        g.user = user
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
