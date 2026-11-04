from datetime import datetime, timezone
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
    __table_args__ = (db.UniqueConstraint('tenant_id','name'), db.UniqueConstraint('tenant_id','id'),)

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
    __table_args__ = (
        db.ForeignKeyConstraint(['tenant_id','role_id'],['roles.tenant_id','roles.id']),
        db.UniqueConstraint('tenant_id','user_id'),
    )
