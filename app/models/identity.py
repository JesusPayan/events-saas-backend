from datetime import datetime, timezone

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from app.extensions import db

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)

class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('tenants.id'), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    __table_args__ = (
    db.UniqueConstraint(
        'tenant_id',
        'name',
        name='uq_roles_tenant_name'
    ),
    db.UniqueConstraint(
        'tenant_id',
        'id',
        name='uq_roles_tenant_id'
    ),
)

class Permission(db.Model):
    __tablename__ = 'permissions'
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    code = db.Column(db.String(100), nullable=False, unique=True)

class RolePermission(db.Model):
    __tablename__ = 'role_permissions'
    role_id = db.Column(db.BigInteger, db.ForeignKey('roles.id',ondelete='CASCADE'), primary_key=True)
    permission_id = db.Column(db.BigInteger, db.ForeignKey('permissions.id',ondelete='CASCADE'), primary_key=True)

class Membership(db.Model):
    __tablename__ = 'memberships'
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('tenants.id'), nullable=False)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False)
    role_id = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='active')
    # Rol «provider»: el usuario solo ve las partidas de este proveedor.
    provider_id = db.Column(db.BigInteger, nullable=True)
    __table_args__ = (
    db.ForeignKeyConstraint(
        ['tenant_id', 'role_id'],
        ['roles.tenant_id', 'roles.id'],
        name='fk_membership_role_same_tenant'
    ),
    db.UniqueConstraint(
        'tenant_id',
        'user_id',
        name='uq_memberships_tenant_user'
    ),
    db.ForeignKeyConstraint(
        ['tenant_id', 'provider_id'],
        ['providers.tenant_id', 'providers.id'],
        name='fk_membership_provider_same_tenant'
    ),
)

class TenantInvitation(db.Model):
    """Invitación de un correo a una empresa con un rol predefinido.

    Solo se guarda el hash SHA-256 del token: el enlace en claro existe únicamente
    en el correo enviado (y en la respuesta inmediata a quien invita).
    """
    __tablename__ = 'tenant_invitations'
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('tenants.id'), nullable=False, index=True)
    email = db.Column(db.String(254), nullable=False)
    role_key = db.Column(db.String(30), nullable=False)
    provider_id = db.Column(db.BigInteger, nullable=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    invited_by = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False)
    accepted_user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    expires_at = db.Column(db.DateTime, nullable=False)
    accepted_at = db.Column(db.DateTime)
    __table_args__ = (
        db.CheckConstraint("status IN ('pending','accepted','revoked')", name='ck_tenant_invitation_status'),
        db.Index('ix_tenant_invitations_tenant_email', 'tenant_id', 'email'),
        db.ForeignKeyConstraint(['tenant_id', 'provider_id'], ['providers.tenant_id', 'providers.id'],
                                name='fk_tenant_invitation_provider'),
    )
