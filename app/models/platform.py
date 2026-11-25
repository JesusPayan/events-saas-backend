"""ROLES-01: roles administrativos con alcance, auditoría, accesos delegados y referidos.

Alcances:
- ``platform``: roles globales (dueño, administrador, promotor y los reservados
  soporte, finanzas y auditoría). Viven en ``platform_role_assignments``.
- ``tenant``: roles internos de cada organización. Siguen en ``memberships``.

Una persona puede tener varias asignaciones de plataforma activas y varias
membresías; cada permiso se evalúa en el alcance de la operación.
"""
from app.extensions import db
from app.models.identity import now

_PK = db.BigInteger().with_variant(db.Integer, "sqlite")

PLATFORM_ROLE_KEYS = ("platform_owner", "platform_admin", "promoter", "support", "finance", "auditor")


class PlatformRoleAssignment(db.Model):
    __tablename__ = "platform_role_assignments"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    role_key = db.Column(db.String(30), nullable=False)
    scope_type = db.Column(db.String(20), nullable=False, default="platform")
    status = db.Column(db.String(20), nullable=False, default="active")
    # 1 mientras está activa; NULL al revocar. Permite UNIQUE(user, rol, active_flag).
    active_flag = db.Column(db.SmallInteger, nullable=True, default=1)
    granted_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    granted_at = db.Column(db.DateTime, nullable=False, default=now)
    revoked_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (
        db.CheckConstraint(
            "role_key IN ('platform_owner','platform_admin','promoter','support','finance','auditor')",
            name="ck_platform_role_key"),
        db.CheckConstraint("status IN ('active','revoked')", name="ck_platform_role_status"),
        db.CheckConstraint("scope_type IN ('platform')", name="ck_platform_role_scope"),
        db.UniqueConstraint("user_id", "role_key", "active_flag", name="uq_platform_role_active"),
        db.Index("ix_platform_roles_role_status", "role_key", "status"),
    )


class PlatformInvitation(db.Model):
    """Invitación a un rol de plataforma para personas sin cuenta (solo hash del token)."""
    __tablename__ = "platform_invitations"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    email = db.Column(db.String(254), nullable=False)
    role_key = db.Column(db.String(30), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    invited_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    accepted_user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    expires_at = db.Column(db.DateTime, nullable=False)
    accepted_at = db.Column(db.DateTime)
    __table_args__ = (
        db.CheckConstraint("status IN ('pending','accepted','revoked')", name="ck_platform_invitation_status"),
        db.Index("ix_platform_invitations_email", "email"),
    )


class AuditEvent(db.Model):
    """Bitácora de acciones sensibles: actor, acción, alcance y fecha."""
    __tablename__ = "audit_events"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    actor_user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(60), nullable=False)
    scope_type = db.Column(db.String(20), nullable=False)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), nullable=True)
    target_type = db.Column(db.String(40), nullable=True)
    target_id = db.Column(db.String(64), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    __table_args__ = (
        db.CheckConstraint("scope_type IN ('platform','tenant')", name="ck_audit_scope"),
        db.Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        db.Index("ix_audit_events_action_created", "action", "created_at"),
        db.Index("ix_audit_events_actor", "actor_user_id"),
    )


class TenantAccessGrant(db.Model):
    """Acceso temporal de solo lectura que el administrador de una organización
    concede a soporte de plataforma o a un promotor (capacitación)."""
    __tablename__ = "tenant_access_grants"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), nullable=False)
    grantee_user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    purpose = db.Column(db.String(20), nullable=False)
    access_level = db.Column(db.String(20), nullable=False, default="read_only")
    reason = db.Column(db.String(500), nullable=True)
    granted_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    granted_at = db.Column(db.DateTime, nullable=False, default=now)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_by = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (
        db.CheckConstraint("purpose IN ('support','training')", name="ck_access_grant_purpose"),
        db.CheckConstraint("access_level IN ('read_only')", name="ck_access_grant_level"),
        db.Index("ix_access_grants_tenant_user", "tenant_id", "grantee_user_id"),
    )


class PromoterReferralCode(db.Model):
    __tablename__ = "promoter_referral_codes"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    promoter_user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False, unique=True)
    code = db.Column(db.String(16), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)


class PromoterProspect(db.Model):
    __tablename__ = "promoter_prospects"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    promoter_user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    company_name = db.Column(db.String(180), nullable=False)
    contact_name = db.Column(db.String(180), nullable=True)
    contact_email = db.Column(db.String(254), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.String(1000), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="prospect")
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), nullable=True)
    invited_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    __table_args__ = (
        db.CheckConstraint("status IN ('prospect','invited','registered','discarded')",
                           name="ck_promoter_prospect_status"),
        db.Index("ix_promoter_prospects_promoter", "promoter_user_id"),
        db.Index("ix_promoter_prospects_email", "contact_email"),
    )


class TenantReferral(db.Model):
    """Organización dada de alta con el enlace de un promotor (sin acceso a sus datos)."""
    __tablename__ = "tenant_referrals"
    id = db.Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, db.ForeignKey("tenants.id"), nullable=False, unique=True)
    promoter_user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    prospect_id = db.Column(db.BigInteger, db.ForeignKey("promoter_prospects.id"), nullable=True)
    code = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    __table_args__ = (db.Index("ix_tenant_referrals_promoter", "promoter_user_id"),)
