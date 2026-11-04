from flask import Blueprint, request, jsonify, g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.models import Tenant
from app.models.identity import User, Role, Permission, RolePermission, Membership
from app.security import authenticate, tenant_permission, issue_token
from datetime import datetime, timedelta
bp = Blueprint('auth', __name__)

@bp.post('/auth/register')
def register():
    data = request.get_json(silent=True) or {}
    print("Register request received:", data)
    if not isinstance(data, dict):
        print("Invalid JSON data")
        return jsonify(error="invalid_json"), 400
   # Payan.202020
    email = data.get("email", "")
    password = data.get("password", "")
    slug = data.get("slug", "")
    name = data.get("company_name", "")
    if not all(isinstance(v, str) for v in
           (email, password, slug, name)):
        print("Invalid registration data")
        return jsonify(error="invalid_registration"), 400
    try:
        #Creamos un nuevo tenant
        tenant = Tenant(name=name, slug=slug, status='active')
        print(f"Creating tenant: {tenant}")
        #creamos un nuevo 
        user = User(
            email=email, 
            password_hash=generate_password_hash(password),
            is_active = True,
            created_at = datetime.now()

            )
        db.session.add(user) 
        db.session.flush()
        db.session.commit()
        #and db.session.add(tenant):
        #print("Registros Guardados Exitosamente")

        db.session.add_all([tenant,user]); 
        db.session.flush()
        role = Role(tenant_id=tenant.id, name='owner'); db.session.add(role); db.session.flush()
        for code in (
    'tenant.read',
    'members.read',
    'clients.read',
    'clients.create',
    'clients.update'
):
            perm = db.session.scalar(select(Permission).where(Permission.code == code))
            if perm is None:
                perm = Permission(code=code); db.session.add(perm); db.session.flush()
            db.session.add(RolePermission(role_id=role.id,permission_id=perm.id))
        db.session.add(Membership(tenant_id=tenant.id,user_id=user.id,role_id=role.id))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error='registration_conflict'), 409
    except Exception:
        db.session.rollback()
        #current_app.logger.exception("Error al registrar empresa")
        return jsonify(error="internal_server_error"), 500
    return jsonify(user_id=user.id, tenant_id=tenant.id), 201

@bp.post('/auth/login')
def login():
    print("Login request received")
    data = request.get_json(silent=True) or {}
    email = str(data.get('email','')).strip().lower()
    user = db.session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not check_password_hash(user.password_hash, str(data.get('password',''))):
        return jsonify(error='invalid_credentials'), 401
    return jsonify(access_token=issue_token(user.id),token_type='Bearer',expires_in=3600),200

@bp.get('/auth/me')
@authenticate
def me():
    memberships = db.session.scalars(select(Membership).where(Membership.user_id == g.user.id,Membership.status == 'active')).all()
    return jsonify(id=g.user.id,email=g.user.email,tenants=[m.tenant_id for m in memberships])

@bp.get('/tenants/current')
@tenant_permission('tenant.read')
def current_tenant():
    tenant = db.session.get(Tenant,g.tenant_id)
    return jsonify(id=tenant.id,name=tenant.name,slug=tenant.slug)

@bp.get('/memberships')
@tenant_permission('members.read')
def members():
    memberships = db.session.scalars(select(Membership).where(Membership.tenant_id == g.tenant_id)).all()
    return jsonify(items=[{'id':m.id,'user_id':m.user_id,'role_id':m.role_id,'status':m.status} for m in memberships])
@bp.get('/auth/permissions')
@tenant_permission('tenant.read')
def get_permissions():
    """
    Obtiene los permisos del usuario autenticado
    dentro de la empresa seleccionada.
    """

    membership = db.session.scalar(
        select(Membership).where(
            Membership.user_id == g.user.id,
            Membership.tenant_id == g.tenant_id,
            Membership.status == 'active'
        )
    )

    if membership is None:
        return jsonify(error='membership_not_found'), 403

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

